"""Security tests: fail-closed auth, internal client_id, HMAC signing, IP allowlist, rate limits."""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trade_order_engine.api import create_app
from trade_order_engine.config import Settings
from trade_order_engine.security import (
    IPAllowlist,
    SlidingWindowRateLimiter,
    generate_secret,
    sign_request,
    verify_api_key,
)

_API_KEY = "secret-order-key-1"
_API_KEY_2 = "secret-order-key-2"
_HMAC_SECRET = "secret-hmac-signing-key"
_INTERNAL_CLIENT = "CLIENT01"

_VALID_ORDER = {
    "uniq_no": 676,
    "contract": "NIFTY2690823850CE",
    "side": 2,
    "lot": 5,
    "price_type": "LIMIT",
    "stg_id": 763,
    "price": "275.55",
}


class TestFailClosedAndApiKeyAuth:
    def test_startup_refuses_to_boot_without_internal_client_id(self, tmp_path: Path) -> None:
        app = create_app(
            Settings(
                orderbook_file_path=tmp_path / "OrderBook.txt",
                api_keys=(_API_KEY,),
            )
        )
        with pytest.raises(RuntimeError, match="ORDER_CLIENT_ID"):
            with TestClient(app):
                pass

    def test_startup_refuses_to_boot_when_auth_enabled_without_key(self, tmp_path: Path) -> None:
        app = create_app(
            Settings(
                orderbook_file_path=tmp_path / "OrderBook.txt",
                client_id=_INTERNAL_CLIENT,
            )
        )
        with pytest.raises(RuntimeError, match="no API key is configured"):
            with TestClient(app):
                pass

    def test_requests_fail_closed_with_503_if_missing_key_or_client_id(
        self,
        tmp_path: Path,
    ) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"

        app_no_key = create_app(
            Settings(orderbook_file_path=orderbook_path, client_id=_INTERNAL_CLIENT)
        )
        resp = TestClient(app_no_key).post(
            "/orders",
            json=_VALID_ORDER,
            headers={"X-API-Key": "anything"},
        )
        assert resp.status_code == 503

        app_no_client = create_app(
            Settings(orderbook_file_path=orderbook_path, api_keys=(_API_KEY,))
        )
        resp2 = TestClient(app_no_client).post(
            "/orders",
            json=_VALID_ORDER,
            headers={"X-API-Key": _API_KEY},
        )
        assert resp2.status_code == 503
        assert not orderbook_path.exists()

    def test_all_order_endpoints_reject_missing_or_wrong_api_key(self, tmp_path: Path) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"
        app = create_app(
            Settings(
                orderbook_file_path=orderbook_path,
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                rate_limit_per_minute=0,
            )
        )
        client = TestClient(app)

        for headers in ({}, {"X-API-Key": "wrong"}, {"Authorization": "Bearer wrong"}):
            assert client.post("/orders", json=_VALID_ORDER, headers=headers).status_code == 401
            assert (
                client.post(
                    "/orders/batch",
                    json={"orders": [_VALID_ORDER]},
                    headers=headers,
                ).status_code
                == 401
            )
            assert client.get("/orders", headers=headers).status_code == 401
            assert client.get("/orders/676", headers=headers).status_code == 401
            assert client.patch("/orders/676", json={"price": "280"}, headers=headers).status_code == 401
            assert client.delete("/orders/676", headers=headers).status_code == 401

        assert not orderbook_path.exists()

    def test_accepts_x_api_key_bearer_and_rotated_keys(self, tmp_path: Path) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"
        app = create_app(
            Settings(
                orderbook_file_path=orderbook_path,
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY, _API_KEY_2),
                rate_limit_per_minute=0,
            )
        )
        with TestClient(app) as client:
            r1 = client.post("/orders", json=_VALID_ORDER, headers={"X-API-Key": _API_KEY})
            assert r1.status_code == 201

            r2 = client.patch(
                "/orders/676",
                json={"price": "276.00"},
                headers={"Authorization": f"Bearer {_API_KEY_2}"},
            )
            assert r2.status_code == 200

        mode = stat.S_IMODE(orderbook_path.stat().st_mode)
        assert mode == 0o600

    def test_generate_secret_and_constant_time_verify(self) -> None:
        token = generate_secret()
        assert len(token) >= 40
        assert verify_api_key(token, (token,))
        assert not verify_api_key("wrong", (token,))
        assert not verify_api_key(None, (token,))


class TestHmacRequestSigning:
    def _signed_headers(
        self,
        method: str,
        path_with_query: str,
        body: bytes = b"",
        *,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        ts, sig = sign_request(
            secret=_HMAC_SECRET,
            method=method,
            path_with_query=path_with_query,
            body=body,
            timestamp=timestamp,
        )
        headers = {
            "X-API-Key": _API_KEY,
            "X-Timestamp": ts,
            "X-Signature": sig,
        }
        if body:
            headers["Content-Type"] = "application/json"
        return headers

    def test_signed_lifecycle_succeeds_and_tampering_or_replay_is_blocked(
        self,
        tmp_path: Path,
    ) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"
        app = create_app(
            Settings(
                orderbook_file_path=orderbook_path,
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                hmac_secret=_HMAC_SECRET,
                hmac_max_skew_seconds=30,
                rate_limit_per_minute=0,
            )
        )

        with TestClient(app) as client:
            raw_body = json.dumps(_VALID_ORDER).encode("utf-8")

            # Missing HMAC headers -> 401
            assert (
                client.post(
                    "/orders",
                    content=raw_body,
                    headers={"X-API-Key": _API_KEY, "Content-Type": "application/json"},
                ).status_code
                == 401
            )

            # Expired timestamp (replay attack) -> 401
            stale_headers = self._signed_headers(
                "POST",
                "/orders",
                raw_body,
                timestamp=int(time.time()) - 120,
            )
            assert client.post("/orders", content=raw_body, headers=stale_headers).status_code == 401

            # Tampered body after signing -> 401
            valid_headers = self._signed_headers("POST", "/orders", raw_body)
            tampered_body = json.dumps({**_VALID_ORDER, "lot": 500}).encode("utf-8")
            assert (
                client.post("/orders", content=tampered_body, headers=valid_headers).status_code
                == 401
            )
            assert not orderbook_path.exists()

            # Legitimate signed POST -> 201
            ok_post = client.post("/orders", content=raw_body, headers=valid_headers)
            assert ok_post.status_code == 201

            # Legitimate signed GET with query params -> 200; mismatched query -> 401
            get_headers = self._signed_headers("GET", "/orders?stg_id=763")
            assert client.get("/orders?stg_id=763", headers=get_headers).status_code == 200
            assert client.get("/orders?stg_id=999", headers=get_headers).status_code == 401

            # Legitimate signed PATCH & DELETE -> 200
            mod_body = json.dumps({"price": "276.50"}).encode("utf-8")
            mod_headers = self._signed_headers("PATCH", "/orders/676", mod_body)
            assert client.patch("/orders/676", content=mod_body, headers=mod_headers).status_code == 200

            del_headers = self._signed_headers("DELETE", "/orders/676")
            assert client.delete("/orders/676", headers=del_headers).status_code == 200


class TestIpAllowlistAndProxySafety:
    def test_ip_allowlist_unit_and_proxy_spoof_resistance(self) -> None:
        allowlist = IPAllowlist(
            ("203.0.113.42", "100.64.0.0/10"),
            trust_proxy_headers=True,
            trusted_proxies=("127.0.0.1/32",),
        )
        assert allowlist.is_allowed("203.0.113.42")
        assert allowlist.is_allowed("::ffff:203.0.113.42")
        assert allowlist.is_allowed("100.101.5.9")
        assert not allowlist.is_allowed("198.51.100.7")
        assert not allowlist.is_allowed("not-an-ip")

        # Direct untrusted peer cannot spoof X-Forwarded-For
        spoofed = allowlist.resolve_client_ip(
            "198.51.100.7",
            x_forwarded_for="203.0.113.42",
        )
        assert spoofed == "198.51.100.7"
        assert not allowlist.is_allowed(spoofed)

        # Trusted proxy forwarding a spoofed left entry still resolves actual rightmost client IP
        chained = allowlist.resolve_client_ip(
            "127.0.0.1",
            x_forwarded_for="203.0.113.42, 198.51.100.7",
        )
        assert chained == "198.51.100.7"
        assert not allowlist.is_allowed(chained)

        # Legitimate trusted proxy forwarding authorized client IP succeeds
        legit = allowlist.resolve_client_ip(
            "127.0.0.1",
            x_forwarded_for="203.0.113.42",
        )
        assert legit == "203.0.113.42"
        assert allowlist.is_allowed(legit)

    def test_ip_allowlist_middleware_blocks_unapproved_ip(self, tmp_path: Path) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"
        app = create_app(
            Settings(
                orderbook_file_path=orderbook_path,
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                allowed_ips=("203.0.113.42",),
                rate_limit_per_minute=0,
            )
        )

        blocked_client = TestClient(
            app,
            client=("198.51.100.7", 50000),
            headers={"X-API-Key": _API_KEY},
        )
        resp = blocked_client.post("/orders", json=_VALID_ORDER)
        assert resp.status_code == 403
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert not orderbook_path.exists()

        allowed_client = TestClient(
            app,
            client=("203.0.113.42", 50000),
            headers={"X-API-Key": _API_KEY},
        )
        ok_resp = allowed_client.post("/orders", json=_VALID_ORDER)
        assert ok_resp.status_code == 201


class TestRateLimitIsolationAndHardening:
    def test_rate_limiter_enforces_limit_and_recovers_after_window(self) -> None:
        now = [100.0]
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0, clock=lambda: now[0])

        assert limiter.allow("ip1") == (True, 0)
        assert limiter.allow("ip1") == (True, 0)
        allowed, retry_after = limiter.allow("ip1")
        assert not allowed
        assert retry_after >= 1

        now[0] += 61.0
        assert limiter.allow("ip1") == (True, 0)

    def test_rate_limit_middleware_returns_429(self, tmp_path: Path) -> None:
        app = create_app(
            Settings(
                orderbook_file_path=tmp_path / "OrderBook.txt",
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                rate_limit_per_minute=2,
            )
        )
        client = TestClient(app, headers={"X-API-Key": _API_KEY})

        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        limited = client.get("/health")
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

    def test_internal_client_isolation_hides_and_protects_other_clients_rows(
        self,
        tmp_path: Path,
    ) -> None:
        orderbook_path = tmp_path / "OrderBook.txt"
        orderbook_path.write_text(
            "901,NIFTY2690823850CE,2,5,275.55,L,OTHER_CLIENT,10,\n",
            encoding="utf-8",
        )
        app = create_app(
            Settings(
                orderbook_file_path=orderbook_path,
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                rate_limit_per_minute=0,
            )
        )
        client = TestClient(app, headers={"X-API-Key": _API_KEY})

        listed = client.get("/orders")
        assert listed.status_code == 200
        assert listed.json()["count"] == 0
        assert "OTHER_CLIENT" not in listed.text

        assert client.get("/orders/901").status_code == 403
        assert client.patch("/orders/901", json={"price": "280.00"}).status_code == 403
        assert client.delete("/orders/901").status_code == 403

    def test_docs_disabled_by_default_and_body_size_cap_enforced(self, tmp_path: Path) -> None:
        app = create_app(
            Settings(
                orderbook_file_path=tmp_path / "OrderBook.txt",
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                max_body_bytes=64,
                enable_docs=False,
                rate_limit_per_minute=0,
            )
        )
        client = TestClient(app, headers={"X-API-Key": _API_KEY})

        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

        oversized = client.post("/orders", json=_VALID_ORDER)
        assert oversized.status_code == 413
        assert oversized.headers["X-Frame-Options"] == "DENY"
        assert oversized.headers["Cache-Control"] == "no-store"

        dev_app = create_app(
            Settings(
                orderbook_file_path=tmp_path / "OrderBook.txt",
                client_id=_INTERNAL_CLIENT,
                api_keys=(_API_KEY,),
                enable_docs=True,
                rate_limit_per_minute=0,
            )
        )
        dev_client = TestClient(dev_app)
        assert dev_client.get("/docs").status_code == 200

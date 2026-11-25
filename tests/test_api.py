"""API integration tests for validating orders and writing headerless `.txt` rows."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from trade_order_engine.api import create_app
from trade_order_engine.config import Settings

_TEST_API_KEY = "test-super-secret-api-key"
_INTERNAL_CLIENT_ID = "CLIENT01"


def _make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    orderbook_path = tmp_path / "OrderBook.txt"
    app = create_app(
        Settings(
            orderbook_file_path=orderbook_path,
            client_id=_INTERNAL_CLIENT_ID,
            api_keys=(_TEST_API_KEY,),
            rate_limit_per_minute=0,
        )
    )
    return TestClient(app, headers={"X-API-Key": _TEST_API_KEY}), orderbook_path


class TestHealthEndpoint:
    def test_health_is_minimal_and_does_not_leak_paths_or_client_id(self, tmp_path: Path) -> None:
        client, orderbook_path = _make_client(tmp_path)

        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert str(orderbook_path) not in resp.text
        assert _INTERNAL_CLIENT_ID not in resp.text

        post_resp = client.post(
            "/orders",
            json={
                "uniq_no": 676,
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price_type": "LIMIT",
                "stg_id": 763,
                "price": "275.55",
                "note": "entry",
            },
        )
        assert post_resp.status_code == 201
        assert _INTERNAL_CLIENT_ID not in post_resp.text
        assert orderbook_path.exists()


class TestSingleOrderEndpoint:
    def test_fire_valid_limit_order_writes_exact_headerless_txt_row(
        self,
        tmp_path: Path,
    ) -> None:
        client, orderbook_path = _make_client(tmp_path)

        resp = client.post(
            "/orders",
            json={
                "uniq_no": 676,
                "contract": "nifty2690823850ce",
                "side": "SELL",
                "lot": 5,
                "price_type": "LIMIT",
                "price": "275.55",
                "stg_id": 763,
                "note": "leg1",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body == {
            "uniq_no": 676,
            "contract": "NIFTY2690823850CE",
            "side": 2,
            "side_name": "SELL",
            "lot": 5,
            "signed_lot": -5,
            "price": "275.55",
            "price_type": "LIMIT",
            "order_type": "L",
            "action": "PLACE",
            "stg_id": 763,
            "note": "leg1",
        }
        assert "client_id" not in body
        assert "raw_line" not in body
        assert _INTERNAL_CLIENT_ID not in resp.text

        # Headerless 9-field row: UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE
        assert orderbook_path.read_text(encoding="utf-8").splitlines() == [
            f"676,NIFTY2690823850CE,2,5,275.55,L,{_INTERNAL_CLIENT_ID},763,leg1",
        ]

    def test_auto_generates_uniq_no_and_stg_id_when_omitted(self, tmp_path: Path) -> None:
        client, orderbook_path = _make_client(tmp_path)

        resp = client.post(
            "/orders",
            json={
                "CONTRACT": "NIFTY2690823850PE",
                "BUY/SELL": 1,
                "LOT": 2,
                "PRICE": "274.65",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["uniq_no"] > 0
        assert body["stg_id"] > 0
        assert body["side"] == 1
        assert body["order_type"] == "L"
        assert body["price_type"] == "LIMIT"
        assert body["note"] == ""
        assert orderbook_path.exists()

    def test_market_order_writes_L_with_price_0_and_rejects_nonzero_or_sl(
        self,
        tmp_path: Path,
    ) -> None:
        client, orderbook_path = _make_client(tmp_path)

        # Market order with explicit price=0 writes PRICE=0 and ORDER_TYPE='L'
        resp = client.post(
            "/orders",
            json={
                "uniq_no": 676,
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price_type": "MARKET",
                "price": "0",
                "stg_id": 763,
                "note": "275.55",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["price"] == "0"
        assert body["price_type"] == "MARKET"
        assert body["order_type"] == "L"
        assert body["note"] == "275.55"

        # Market order omitting price defaults to 0 and writes ORDER_TYPE='L'
        resp_default = client.post(
            "/orders",
            json={
                "uniq_no": 114,
                "contract": "NIFTY2690823850PE",
                "side": 2,
                "lot": 5,
                "price_type": "M",
                "stg_id": 763,
                "note": "275.55",
            },
        )
        assert resp_default.status_code == 201
        assert resp_default.json()["price"] == "0"
        assert resp_default.json()["order_type"] == "L"

        # Market order with nonzero price rejected (422)
        bad_mkt = client.post(
            "/orders",
            json={
                "uniq_no": 103,
                "contract": "NIFTY2690823850CE",
                "side": "BUY",
                "lot": 1,
                "price_type": "MARKET",
                "price": "275.55",
            },
        )
        assert bad_mkt.status_code == 422

        # SL and SLM rejected (422)
        for disallowed in ("SL", "SLM"):
            bad_type = client.post(
                "/orders",
                json={
                    "contract": "NIFTY2690823850CE",
                    "side": "BUY",
                    "lot": 1,
                    "price_type": disallowed,
                    "price": "275.55",
                },
            )
            assert bad_type.status_code == 422

        assert orderbook_path.read_text(encoding="utf-8").splitlines() == [
            f"676,NIFTY2690823850CE,2,5,0,L,{_INTERNAL_CLIENT_ID},763,275.55",
            f"114,NIFTY2690823850PE,2,5,0,L,{_INTERNAL_CLIENT_ID},763,275.55",
        ]

        # Reading back market order via GET preserves MARKET classification
        fetched = client.get("/orders/676")
        assert fetched.status_code == 200
        assert fetched.json()["price_type"] == "MARKET"
        assert fetched.json()["order_type"] == "L"
        assert fetched.json()["price"] == "0"
        assert fetched.json()["note"] == "275.55"

    def test_invalid_orders_and_public_client_id_rejected_without_touching_file(
        self,
        tmp_path: Path,
    ) -> None:
        client, orderbook_path = _make_client(tmp_path)

        invalid_payloads = [
            # Passing client_id or ID publicly is forbidden
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "client_id": "ANYCLIENT",
                "price": "275.55",
            },
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "ID": "ANYCLIENT",
                "price": "275.55",
            },
            # Invalid contract format
            {
                "contract": "INVALID_CONTRACT",
                "side": 1,
                "lot": 5,
                "price": "275.55",
            },
            # Invalid side
            {
                "contract": "NIFTY2690823850CE",
                "side": 9,
                "lot": 5,
                "price": "275.55",
            },
            # LIMIT order with price == 0
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price_type": "LIMIT",
                "price": "0",
            },
            # Zero lot
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 0,
                "price": "275.55",
            },
            # CSV-unsafe note
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price": "275.55",
                "note": "bad,comma",
            },
            # Unknown extra field
            {
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price": "275.55",
                "unexpected_field": 123,
            },
        ]

        for payload in invalid_payloads:
            resp = client.post("/orders", json=payload)
            assert resp.status_code == 422

        assert not orderbook_path.exists()


class TestBatchAndListEndpoints:
    def test_batch_straddle_shares_stg_id_and_writes_atomically(self, tmp_path: Path) -> None:
        client, orderbook_path = _make_client(tmp_path)

        resp = client.post(
            "/orders/batch",
            json={
                "orders": [
                    {
                        "uniq_no": 676,
                        "contract": "NIFTY2690823850CE",
                        "side": 2,
                        "lot": 5,
                        "price_type": "MARKET",
                        "note": "275.55",
                    },
                    {
                        "uniq_no": 114,
                        "contract": "NIFTY2690823850PE",
                        "side": 2,
                        "lot": 5,
                        "price_type": "MARKET",
                        "note": "275.55",
                    },
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["count"] == 2
        assert "file_path" not in body
        assert _INTERNAL_CLIENT_ID not in resp.text
        leg1, leg2 = body["orders"]
        assert leg1["stg_id"] == leg2["stg_id"]

        lines = orderbook_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2  # headerless: 2 rows only

    def test_batch_with_one_invalid_leg_writes_nothing(self, tmp_path: Path) -> None:
        client, orderbook_path = _make_client(tmp_path)

        resp = client.post(
            "/orders/batch",
            json={
                "stg_id": 763,
                "orders": [
                    {
                        "contract": "NIFTY2690823850CE",
                        "side": 2,
                        "lot": 5,
                        "price": "275.55",
                    },
                    {
                        "contract": "BAD_SYMBOL",
                        "side": 2,
                        "lot": 5,
                        "price": "275.55",
                    },
                ],
            },
        )
        assert resp.status_code == 422
        assert not orderbook_path.exists()

    def test_list_orders_with_filters(self, tmp_path: Path) -> None:
        client, _ = _make_client(tmp_path)

        client.post(
            "/orders/batch",
            json={
                "orders": [
                    {
                        "uniq_no": 676,
                        "contract": "NIFTY2690823850CE",
                        "side": 2,
                        "lot": 5,
                        "stg_id": 763,
                        "price": "275.55",
                    },
                    {
                        "uniq_no": 785,
                        "contract": "NIFTY2690823850CE",
                        "side": 1,
                        "lot": 5,
                        "stg_id": 763,
                        "price": "277.05",
                    },
                    {
                        "uniq_no": 8790,
                        "contract": "NIFTY2690823850CE",
                        "side": 2,
                        "lot": 1,
                        "stg_id": 421,
                        "price": "277.45",
                    },
                ]
            },
        )

        all_resp = client.get("/orders")
        assert all_resp.status_code == 200
        assert all_resp.json()["count"] == 3
        assert "file_path" not in all_resp.json()
        assert _INTERNAL_CLIENT_ID not in all_resp.text

        by_stg = client.get("/orders", params={"stg_id": 763})
        assert by_stg.json()["count"] == 2

        by_side = client.get("/orders", params={"side": "BUY"})
        assert by_side.json()["count"] == 1
        assert by_side.json()["orders"][0]["uniq_no"] == 785

        limited = client.get("/orders", params={"limit": 2})
        assert limited.json()["count"] == 2

        bad_side = client.get("/orders", params={"side": "INVALID"})
        assert bad_side.status_code == 422


class TestModifyAndCancelLifecycle:
    def test_place_modify_cancel_full_lifecycle_always_L_and_flips_side_on_cancel(
        self,
        tmp_path: Path,
    ) -> None:
        client, orderbook_path = _make_client(tmp_path)

        # 1. Place SELL Limit order (ORDER_TYPE='L', side=2)
        place_resp = client.post(
            "/orders",
            json={
                "uniq_no": 676,
                "contract": "NIFTY2690823850CE",
                "side": 2,
                "lot": 5,
                "price_type": "LIMIT",
                "price": "275.55",
                "stg_id": 763,
                "note": "init",
            },
        )
        assert place_resp.status_code == 201
        assert place_resp.json()["order_type"] == "L"
        assert place_resp.json()["action"] == "PLACE"
        assert place_resp.json()["side"] == 2

        # 2. Modify price (same uniq_no=676, same side=2, ORDER_TYPE still 'L')
        mod1_resp = client.patch(
            "/orders/676",
            json={"lot": 10, "price": "276.25"},
        )
        assert mod1_resp.status_code == 200
        mod1_body = mod1_resp.json()
        assert mod1_body["order_type"] == "L"
        assert mod1_body["action"] == "MODIFY"
        assert mod1_body["side"] == 2
        assert mod1_body["lot"] == 10
        assert _INTERNAL_CLIENT_ID not in mod1_resp.text

        # 3. Second modify changes price & note (still same uniq_no, same side=2, ORDER_TYPE='L')
        mod2_resp = client.patch("/orders/676", json={"price": "277.00", "note": "repriced"})
        assert mod2_resp.status_code == 200
        assert mod2_resp.json()["price"] == "277.00"
        assert mod2_resp.json()["order_type"] == "L"
        assert mod2_resp.json()["side"] == 2

        # GET /orders/676 returns latest modified state without exposing client_id
        get_resp = client.get("/orders/676")
        assert get_resp.status_code == 200
        assert get_resp.json()["price"] == "277.00"
        assert get_resp.json()["order_type"] == "L"
        assert get_resp.json()["action"] == "MODIFY"
        assert _INTERNAL_CLIENT_ID not in get_resp.text

        # 4. Cancel SELL order -> flips side 2 -> 1 (BUY), keeps ORDER_TYPE='L' and all other fields
        cancel_resp = client.delete("/orders/676")
        assert cancel_resp.status_code == 200
        cancel_body = cancel_resp.json()
        assert cancel_body["order_type"] == "L"
        assert cancel_body["action"] == "CANCEL"
        assert cancel_body["side"] == 1
        assert cancel_body["side_name"] == "BUY"
        assert _INTERNAL_CLIENT_ID not in cancel_resp.text

        # Also test BUY -> CANCEL flips side 1 -> 2 (SELL) with ORDER_TYPE='L'
        assert (
            client.post(
                "/orders",
                json={
                    "uniq_no": 700,
                    "contract": "NIFTY2690823850PE",
                    "side": 1,
                    "lot": 3,
                    "price_type": "LIMIT",
                    "price": "150.00",
                    "stg_id": 763,
                    "note": "buy-leg",
                },
            ).status_code
            == 201
        )
        buy_cancel = client.delete("/orders/700")
        assert buy_cancel.status_code == 200
        assert buy_cancel.json()["side"] == 2
        assert buy_cancel.json()["side_name"] == "SELL"
        assert buy_cancel.json()["order_type"] == "L"
        assert buy_cancel.json()["action"] == "CANCEL"

        # Verify exact headerless .txt contents (ORDER_TYPE is ALWAYS 'L'!)
        assert orderbook_path.read_text(encoding="utf-8").splitlines() == [
            f"676,NIFTY2690823850CE,2,5,275.55,L,{_INTERNAL_CLIENT_ID},763,init",
            f"676,NIFTY2690823850CE,2,10,276.25,L,{_INTERNAL_CLIENT_ID},763,init",
            f"676,NIFTY2690823850CE,2,10,277.00,L,{_INTERNAL_CLIENT_ID},763,repriced",
            f"676,NIFTY2690823850CE,1,10,277.00,L,{_INTERNAL_CLIENT_ID},763,repriced",
            f"700,NIFTY2690823850PE,1,3,150.00,L,{_INTERNAL_CLIENT_ID},763,buy-leg",
            f"700,NIFTY2690823850PE,2,3,150.00,L,{_INTERNAL_CLIENT_ID},763,buy-leg",
        ]

        # Filter by lifecycle action in GET /orders
        assert client.get("/orders", params={"action": "PLACE"}).json()["count"] == 2
        assert client.get("/orders", params={"action": "MODIFY"}).json()["count"] == 2
        assert client.get("/orders", params={"action": "CANCEL"}).json()["count"] == 2

        # 5. Further modify or cancel after cancellation returns 409 Conflict
        assert client.patch("/orders/676", json={"price": "278.00"}).status_code == 409
        assert client.delete("/orders/676").status_code == 409
        assert client.delete("/orders/700").status_code == 409
        assert len(orderbook_path.read_text(encoding="utf-8").splitlines()) == 6

    def test_modify_cancel_get_nonexistent_order_returns_404_without_creating_file(
        self,
        tmp_path: Path,
    ) -> None:
        client, orderbook_path = _make_client(tmp_path)

        assert client.get("/orders/999").status_code == 404
        assert client.patch("/orders/999", json={"price": "275.55"}).status_code == 404
        assert client.delete("/orders/999").status_code == 404
        assert not orderbook_path.exists()

    def test_modify_validation_and_duplicate_place_guards(self, tmp_path: Path) -> None:
        client, orderbook_path = _make_client(tmp_path)

        # Place a MARKET order (PRICE=0, ORDER_TYPE='L')
        ok_place = client.post(
            "/orders",
            json={
                "uniq_no": 500,
                "contract": "NIFTY2690823850CE",
                "side": 1,
                "lot": 1,
                "price_type": "MARKET",
                "stg_id": 50,
                "price": "0",
            },
        )
        assert ok_place.status_code == 201

        # Duplicate uniq_no rejected with 409
        dup_place = client.post(
            "/orders",
            json={
                "uniq_no": 500,
                "contract": "NIFTY2690823850PE",
                "side": 1,
                "lot": 1,
                "price": "100.00",
            },
        )
        assert dup_place.status_code == 409

        # Empty modify rejected with 422
        assert client.patch("/orders/500", json={}).status_code == 422

        # Switching MARKET (price=0) to LIMIT without positive price rejected with 422
        assert client.patch("/orders/500", json={"price_type": "LIMIT"}).status_code == 422

        # Trying to set nonzero price while staying MARKET rejected with 422
        assert client.patch("/orders/500", json={"price": "105.50"}).status_code == 422

        # Switching MARKET to LIMIT WITH positive price succeeds (ORDER_TYPE stays 'L')
        good_mod = client.patch("/orders/500", json={"price_type": "LIMIT", "price": "105.50"})
        assert good_mod.status_code == 200
        assert good_mod.json()["price_type"] == "LIMIT"
        assert good_mod.json()["price"] == "105.50"
        assert good_mod.json()["order_type"] == "L"
        assert good_mod.json()["action"] == "MODIFY"

        # Switching LIMIT back to MARKET with nonzero price fails 422; without price resets price to 0
        assert client.patch("/orders/500", json={"price_type": "MARKET", "price": "105.50"}).status_code == 422
        back_to_mkt = client.patch("/orders/500", json={"price_type": "MARKET"})
        assert back_to_mkt.status_code == 200
        assert back_to_mkt.json()["price_type"] == "MARKET"
        assert back_to_mkt.json()["price"] == "0"
        assert back_to_mkt.json()["order_type"] == "L"
        assert back_to_mkt.json()["action"] == "MODIFY"

        assert orderbook_path.read_text(encoding="utf-8").splitlines() == [
            f"500,NIFTY2690823850CE,1,1,0,L,{_INTERNAL_CLIENT_ID},50,",
            f"500,NIFTY2690823850CE,1,1,105.50,L,{_INTERNAL_CLIENT_ID},50,",
            f"500,NIFTY2690823850CE,1,1,0,L,{_INTERNAL_CLIENT_ID},50,",
        ]

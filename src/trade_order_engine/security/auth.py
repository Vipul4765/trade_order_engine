"""Constant-time API key and HMAC-SHA256 request signing helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Sequence


def generate_secret(num_bytes: int = 32) -> str:
    """Generate a cryptographically strong URL-safe secret token."""
    return secrets.token_urlsafe(num_bytes)


def extract_api_key(
    *,
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    """Extract an API key from `X-API-Key` or `Authorization: Bearer <token>`."""
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()

    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()

    return None


def verify_api_key(provided: str | None, valid_keys: Sequence[str]) -> bool:
    """Check `provided` against all `valid_keys` without timing short-circuits."""
    if not provided or not valid_keys:
        return False

    provided_bytes = provided.encode("utf-8")
    matched = False
    for key in valid_keys:
        if not key:
            continue
        matched |= hmac.compare_digest(provided_bytes, key.encode("utf-8"))
    return matched


def build_hmac_payload(
    *,
    timestamp: str,
    method: str,
    path_with_query: str,
    body: bytes,
) -> bytes:
    """Build the canonical byte payload signed by HMAC-SHA256."""
    prefix = f"{timestamp}.{method.upper()}.{path_with_query}.".encode("utf-8")
    return prefix + body


def sign_request(
    *,
    secret: str,
    method: str,
    path_with_query: str,
    body: bytes = b"",
    timestamp: int | None = None,
) -> tuple[str, str]:
    """Produce `(X-Timestamp, X-Signature)` headers for an authorized client."""
    ts = str(int(time.time()) if timestamp is None else int(timestamp))
    payload = build_hmac_payload(
        timestamp=ts,
        method=method,
        path_with_query=path_with_query,
        body=body,
    )
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return ts, signature


def verify_hmac_signature(
    *,
    secret: str,
    timestamp: str | None,
    signature: str | None,
    method: str,
    path_with_query: str,
    body: bytes,
    max_skew_seconds: int = 30,
    now: float | None = None,
) -> tuple[bool, str]:
    """Verify request timestamp freshness and HMAC-SHA256 signature."""
    if not timestamp or not signature:
        return False, "Missing X-Timestamp or X-Signature header"

    try:
        ts_value = int(timestamp.strip())
    except ValueError:
        return False, "Invalid X-Timestamp header"

    current_time = time.time() if now is None else now
    if abs(current_time - ts_value) > max_skew_seconds:
        return False, "Request timestamp expired or outside allowed clock skew"

    expected_payload = build_hmac_payload(
        timestamp=str(ts_value),
        method=method,
        path_with_query=path_with_query,
        body=body,
    )
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        expected_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature.strip().lower(), expected_sig):
        return False, "Invalid request signature"

    return True, ""

"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ORDERBOOK_FILE = Path("data/OrderBook.txt")
DEFAULT_TRUSTED_PROXIES = ("127.0.0.1/32", "::1/128")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean environment value: {raw!r}")


def _parse_csv_tuple(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_int(raw: str | None, *, default: int, minimum: int = 0) -> int:
    if raw is None or not raw.strip():
        return default
    value = int(raw.strip())
    if value < minimum:
        raise ValueError(f"Configuration integer must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime and security settings for `trade_order_engine`.

    `client_id` is configured strictly server-side (`ORDER_CLIENT_ID`) and is
    injected internally when writing `.txt` OrderBook rows — never accepted from
    or exposed in public API requests/responses.
    """

    orderbook_file_path: Path = DEFAULT_ORDERBOOK_FILE
    client_id: str = ""
    auth_enabled: bool = True
    api_keys: tuple[str, ...] = ()
    hmac_secret: str | None = None
    hmac_max_skew_seconds: int = 30
    allowed_ips: tuple[str, ...] = ()
    trust_proxy_headers: bool = False
    trusted_proxies: tuple[str, ...] = DEFAULT_TRUSTED_PROXIES
    rate_limit_per_minute: int = 60
    max_body_bytes: int = 65_536
    enable_docs: bool = False

    def validate_security(self) -> None:
        """Enforce fail-closed configuration before accepting traffic."""
        cleaned_client_id = self.client_id.strip()
        if not cleaned_client_id or not _CLIENT_ID_RE.match(cleaned_client_id):
            raise RuntimeError(
                "Internal client_id is not configured or invalid. "
                "Set ORDER_CLIENT_ID (1-32 alphanumeric/'_'/'-' chars) before starting the server."
            )
        if self.auth_enabled and not self.api_keys:
            raise RuntimeError(
                "Authentication is enabled (ORDER_AUTH_ENABLED=true) but no API key is configured. "
                "Set ORDER_API_KEY (or ORDER_API_KEYS) before starting the server."
            )
        if self.hmac_max_skew_seconds <= 0:
            raise ValueError("hmac_max_skew_seconds must be positive")
        if self.rate_limit_per_minute < 0:
            raise ValueError("rate_limit_per_minute cannot be negative")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables."""
        raw_path = os.getenv("ORDERBOOK_FILE_PATH", "").strip()
        file_path = Path(raw_path) if raw_path else DEFAULT_ORDERBOOK_FILE

        single_key = os.getenv("ORDER_API_KEY", "").strip()
        multi_keys = _parse_csv_tuple(os.getenv("ORDER_API_KEYS"))
        combined_keys = tuple(dict.fromkeys((*([single_key] if single_key else []), *multi_keys)))

        raw_hmac = os.getenv("ORDER_HMAC_SECRET", "").strip()
        trusted_proxies = _parse_csv_tuple(os.getenv("ORDER_TRUSTED_PROXIES"))

        return cls(
            orderbook_file_path=file_path,
            client_id=os.getenv("ORDER_CLIENT_ID", "").strip(),
            auth_enabled=_parse_bool(os.getenv("ORDER_AUTH_ENABLED"), default=True),
            api_keys=combined_keys,
            hmac_secret=raw_hmac or None,
            hmac_max_skew_seconds=_parse_int(
                os.getenv("ORDER_HMAC_MAX_SKEW_SECONDS"),
                default=30,
                minimum=1,
            ),
            allowed_ips=_parse_csv_tuple(os.getenv("ORDER_ALLOWED_IPS")),
            trust_proxy_headers=_parse_bool(
                os.getenv("ORDER_TRUST_PROXY_HEADERS"),
                default=False,
            ),
            trusted_proxies=trusted_proxies or DEFAULT_TRUSTED_PROXIES,
            rate_limit_per_minute=_parse_int(
                os.getenv("ORDER_RATE_LIMIT_PER_MINUTE"),
                default=60,
                minimum=0,
            ),
            max_body_bytes=_parse_int(
                os.getenv("ORDER_MAX_BODY_BYTES"),
                default=65_536,
                minimum=1,
            ),
            enable_docs=_parse_bool(os.getenv("ORDER_ENABLE_DOCS"), default=False),
        )

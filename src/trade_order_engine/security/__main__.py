"""CLI helper to generate cryptographically secure API and HMAC secrets."""

from __future__ import annotations

from trade_order_engine.security.auth import generate_secret


def main() -> None:
    print(f"ORDER_API_KEY={generate_secret(32)}")
    print(f"ORDER_HMAC_SECRET={generate_secret(32)}")


if __name__ == "__main__":
    main()

"""FastAPI application factory with defense-in-depth security controls."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from trade_order_engine.api.routes import health, orders
from trade_order_engine.config import Settings
from trade_order_engine.security.ip_filter import IPAllowlist
from trade_order_engine.security.rate_limit import SlidingWindowRateLimiter
from trade_order_engine.services.order_service import OrderService
from trade_order_engine.storage.orderbook_writer import OrderBookFileStore

logger = logging.getLogger("trade_order_engine.security")
_HTTP_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413)


def _apply_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and wire the secured FastAPI application."""
    active_settings = settings or Settings.from_env()
    store = OrderBookFileStore(active_settings.orderbook_file_path)
    service = OrderService(
        store,
        client_id=active_settings.client_id,
    )
    ip_allowlist = IPAllowlist(
        active_settings.allowed_ips,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        trusted_proxies=active_settings.trusted_proxies,
    )
    rate_limiter = SlidingWindowRateLimiter(active_settings.rate_limit_per_minute)

    @asynccontextmanager
    async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
        active_settings.validate_security()
        yield

    application = FastAPI(
        title="Trade Order Engine API",
        version="0.1.0",
        description="Validate incoming orders and append them to the OrderBook .txt file.",
        lifespan=_lifespan,
        docs_url="/docs" if active_settings.enable_docs else None,
        redoc_url="/redoc" if active_settings.enable_docs else None,
        openapi_url="/openapi.json" if active_settings.enable_docs else None,
    )
    application.state.settings = active_settings
    application.state.orderbook_store = store
    application.state.order_service = service
    application.state.ip_allowlist = ip_allowlist
    application.state.rate_limiter = rate_limiter

    @application.middleware("http")
    async def _security_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        peer_host = request.client.host if request.client else None
        client_ip = ip_allowlist.resolve_client_ip(
            peer_host,
            x_forwarded_for=request.headers.get("X-Forwarded-For"),
            x_real_ip=request.headers.get("X-Real-IP"),
        )
        request.state.client_ip = client_ip

        if not ip_allowlist.is_allowed(client_ip):
            logger.warning("Blocked request from disallowed ip=%s path=%s", client_ip, request.url.path)
            return _apply_security_headers(
                JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Access denied from this IP address"},
                )
            )

        allowed, retry_after = rate_limiter.allow(client_ip)
        if not allowed:
            logger.warning("Rate-limited ip=%s path=%s", client_ip, request.url.path)
            return _apply_security_headers(
                JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
            )

        content_length_raw = request.headers.get("Content-Length")
        if content_length_raw:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                return _apply_security_headers(
                    JSONResponse(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        content={"detail": "Invalid Content-Length header"},
                    )
                )
            if content_length > active_settings.max_body_bytes:
                return _apply_security_headers(
                    JSONResponse(
                        status_code=_HTTP_413,
                        content={"detail": "Request payload too large"},
                    )
                )

        response = await call_next(request)
        return _apply_security_headers(response)

    application.include_router(health.router)
    application.include_router(orders.router)
    return application


app = create_app()

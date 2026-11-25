"""FastAPI security dependencies for authenticated & signed order endpoints."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from trade_order_engine.config import Settings
from trade_order_engine.security.auth import (
    extract_api_key,
    verify_api_key,
    verify_hmac_signature,
)

logger = logging.getLogger("trade_order_engine.security")


async def require_authorized_request(request: Request) -> str:
    """Enforce API key authentication, optional HMAC signature, and body size guard."""
    settings: Settings = request.app.state.settings
    client_ip: str = getattr(request.state, "client_ip", "unknown")

    if not settings.client_id.strip():
        logger.error("Rejected request %s %s: server client_id not configured", request.method, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server internal client_id is not configured",
        )

    if settings.auth_enabled:
        if not settings.api_keys:
            logger.error("Rejected request %s %s: server API key not configured", request.method, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Server authentication is not configured",
            )

        provided_key = extract_api_key(
            x_api_key=request.headers.get("X-API-Key"),
            authorization=request.headers.get("Authorization"),
        )
        if not verify_api_key(provided_key, settings.api_keys):
            logger.warning(
                "Unauthorized API key attempt from ip=%s path=%s %s",
                client_ip,
                request.method,
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    raw_body = await request.body()
    if len(raw_body) > settings.max_body_bytes:
        logger.warning("Rejected oversized payload (%d bytes) from ip=%s", len(raw_body), client_ip)
        raise HTTPException(
            status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
            detail="Request payload too large",
        )

    if settings.hmac_secret:
        path_with_query = (
            f"{request.url.path}?{request.url.query}"
            if request.url.query
            else request.url.path
        )
        ok, reason = verify_hmac_signature(
            secret=settings.hmac_secret,
            timestamp=request.headers.get("X-Timestamp"),
            signature=request.headers.get("X-Signature"),
            method=request.method,
            path_with_query=path_with_query,
            body=raw_body,
            max_skew_seconds=settings.hmac_max_skew_seconds,
        )
        if not ok:
            logger.warning(
                "Rejected HMAC signature from ip=%s path=%s %s: %s",
                client_ip,
                request.method,
                request.url.path,
                reason,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=reason,
            )

    return client_ip

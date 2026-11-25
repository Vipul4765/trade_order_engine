"""Health check routes."""

from __future__ import annotations

from fastapi import APIRouter

from trade_order_engine.schemas.order import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Minimal public liveness check without exposing internal file paths."""
    return HealthResponse(status="ok")

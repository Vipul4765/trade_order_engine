"""Protected order place, modify, cancel, and query routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from trade_order_engine.api.dependencies import require_authorized_request
from trade_order_engine.enums.order import OrderSide, OrderType
from trade_order_engine.exceptions import (
    OrderConflictError,
    OrderForbiddenError,
    OrderNotFoundError,
    OrderValidationError,
)
from trade_order_engine.schemas.order import (
    OrderBatchCreateRequest,
    OrderBatchResponse,
    OrderCreateRequest,
    OrderListResponse,
    OrderModifyRequest,
    OrderResponse,
)
from trade_order_engine.services.order_service import OrderService

logger = logging.getLogger("trade_order_engine.audit")

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(require_authorized_request)],
)
_HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


def _get_order_service(request: Request) -> OrderService:
    return request.app.state.order_service


def _client_ip(request: Request) -> str:
    return getattr(request.state, "client_ip", "unknown")


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def place_order(payload: OrderCreateRequest, request: Request) -> OrderResponse:
    """Validate and place a single order (`ORDER_TYPE='L'`) into the OrderBook `.txt` file."""
    service = _get_order_service(request)
    try:
        record = service.place_order(payload)
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info(
        "action=PLACE ip=%s uniq_no=%s contract=%s side=%s lot=%s price=%s price_type=%s",
        _client_ip(request),
        record.uniq_no,
        record.contract,
        record.side.name,
        record.lot,
        record.price,
        record.price_type.name,
    )
    return OrderResponse.from_record(record)


@router.post(
    "/batch",
    response_model=OrderBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def place_orders_batch(
    payload: OrderBatchCreateRequest,
    request: Request,
) -> OrderBatchResponse:
    """Validate all order legs atomically and append them (`ORDER_TYPE='L'`) to `.txt`."""
    service = _get_order_service(request)
    try:
        records = service.place_orders_batch(payload)
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info(
        "action=PLACE_BATCH ip=%s count=%d uniq_nos=%s",
        _client_ip(request),
        len(records),
        [r.uniq_no for r in records],
    )
    return OrderBatchResponse(
        count=len(records),
        orders=[OrderResponse.from_record(record) for record in records],
    )


@router.get("", response_model=OrderListResponse)
def list_orders(
    request: Request,
    stg_id: int | None = Query(default=None, gt=0, description="Filter by strategy ID (`STG_ID`)"),
    side: str | None = Query(default=None, description="Filter by side: 1/BUY or 2/SELL"),
    order_type: str | None = Query(
        default=None,
        description="Filter by ORDER_TYPE: L/PLACE, M/MODIFY, C/CANCEL",
    ),
    limit: int | None = Query(default=None, gt=0, description="Maximum number of rows to return"),
) -> OrderListResponse:
    """Read back written order rows from the OrderBook `.txt` file."""
    parsed_side: OrderSide | None = None
    if side is not None:
        try:
            parsed_side = OrderSide.from_raw(side)
        except ValueError as exc:
            raise HTTPException(status_code=_HTTP_422, detail=str(exc)) from exc

    parsed_order_type: OrderType | None = None
    if order_type is not None:
        try:
            parsed_order_type = OrderType.from_raw(order_type)
        except ValueError as exc:
            raise HTTPException(status_code=_HTTP_422, detail=str(exc)) from exc

    service = _get_order_service(request)
    records = service.list_orders(
        stg_id=stg_id,
        side=parsed_side,
        order_type=parsed_order_type,
        limit=limit,
    )
    return OrderListResponse(
        count=len(records),
        orders=[OrderResponse.from_record(record) for record in records],
    )


@router.get("/{uniq_no}", response_model=OrderResponse)
def get_order(
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`)"),
) -> OrderResponse:
    """Return the latest recorded state for a single order by `uniq_no`."""
    service = _get_order_service(request)
    try:
        record = service.get_order(uniq_no)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return OrderResponse.from_record(record)


@router.patch("/{uniq_no}", response_model=OrderResponse)
def modify_order(
    payload: OrderModifyRequest,
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`) to modify"),
) -> OrderResponse:
    """Validate and append a MODIFY (`ORDER_TYPE='M'`) row for an active order."""
    service = _get_order_service(request)
    try:
        record = service.modify_order(uniq_no, payload)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrderValidationError as exc:
        raise HTTPException(status_code=_HTTP_422, detail=str(exc)) from exc

    logger.info(
        "action=MODIFY ip=%s uniq_no=%s lot=%s price=%s price_type=%s",
        _client_ip(request),
        record.uniq_no,
        record.lot,
        record.price,
        record.price_type.name,
    )
    return OrderResponse.from_record(record)


@router.delete("/{uniq_no}", response_model=OrderResponse)
def cancel_order(
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`) to cancel"),
) -> OrderResponse:
    """Validate and append a CANCEL (`ORDER_TYPE='C'`) row for an active order."""
    service = _get_order_service(request)
    try:
        record = service.cancel_order(uniq_no)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OrderConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info(
        "action=CANCEL ip=%s uniq_no=%s contract=%s",
        _client_ip(request),
        record.uniq_no,
        record.contract,
    )
    return OrderResponse.from_record(record)

"""Protected order place, modify, cancel, and query routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from trade_order_engine.api.dependencies import require_authorized_request
from trade_order_engine.enums.order import OrderAction, OrderSide
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
    return OrderResponse.from_record(record, action=OrderAction.PLACE)


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
        orders=[OrderResponse.from_record(record, action=OrderAction.PLACE) for record in records],
    )


@router.get("", response_model=OrderListResponse)
def list_orders(
    request: Request,
    stg_id: int | None = Query(default=None, gt=0, description="Filter by strategy ID (`STG_ID`)"),
    side: str | None = Query(default=None, description="Filter by side: 1/BUY or 2/SELL"),
    action: str | None = Query(
        default=None,
        description="Filter by lifecycle action: PLACE, MODIFY, CANCEL",
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

    parsed_action: OrderAction | None = None
    if action is not None:
        try:
            parsed_action = OrderAction.from_raw(action)
        except ValueError as exc:
            raise HTTPException(status_code=_HTTP_422, detail=str(exc)) from exc

    service = _get_order_service(request)
    rows = service.list_orders(
        stg_id=stg_id,
        side=parsed_side,
        action=parsed_action,
        limit=limit,
    )
    return OrderListResponse(
        count=len(rows),
        orders=[OrderResponse.from_record(record, action=row_action) for record, row_action in rows],
    )


@router.get("/{uniq_no}", response_model=OrderResponse)
def get_order(
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`)"),
) -> OrderResponse:
    """Return the latest recorded state for a single order by `uniq_no`."""
    service = _get_order_service(request)
    try:
        record, row_action = service.get_order(uniq_no)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return OrderResponse.from_record(record, action=row_action)


@router.patch("/{uniq_no}", response_model=OrderResponse)
def modify_order(
    payload: OrderModifyRequest,
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`) to modify"),
) -> OrderResponse:
    """Modify an active order: keeps `uniq_no`, same `BUY/SELL` side, and `ORDER_TYPE='L'`."""
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
        "action=MODIFY ip=%s uniq_no=%s side=%s lot=%s price=%s price_type=%s",
        _client_ip(request),
        record.uniq_no,
        record.side.name,
        record.lot,
        record.price,
        record.price_type.name,
    )
    return OrderResponse.from_record(record, action=OrderAction.MODIFY)


@router.delete("/{uniq_no}", response_model=OrderResponse)
def cancel_order(
    request: Request,
    uniq_no: int = Path(..., gt=0, description="Unique order number (`UNIQ NO`) to cancel"),
) -> OrderResponse:
    """Cancel an active order: keeps `uniq_no` & `ORDER_TYPE='L'`, flips `BUY/SELL` (`1 <-> 2`)."""
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
        "action=CANCEL ip=%s uniq_no=%s flipped_side=%s contract=%s",
        _client_ip(request),
        record.uniq_no,
        record.side.name,
        record.contract,
    )
    return OrderResponse.from_record(record, action=OrderAction.CANCEL)

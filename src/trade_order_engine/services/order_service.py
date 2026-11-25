"""Order lifecycle service: place, modify, cancel, query, and `.txt` persistence."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from decimal import Decimal

from trade_order_engine.enums.order import OrderSide, OrderType, PriceType
from trade_order_engine.exceptions import (
    DuplicateOrderError,
    OrderAlreadyCancelledError,
    OrderForbiddenError,
    OrderNotFoundError,
    OrderValidationError,
)
from trade_order_engine.models.order import OrderRecord
from trade_order_engine.schemas.order import (
    OrderBatchCreateRequest,
    OrderCreateRequest,
    OrderModifyRequest,
)
from trade_order_engine.storage.orderbook_writer import OrderBookFileStore


def _default_uniq_no() -> int:
    """Generate a positive unique order number (100..999999)."""
    return secrets.randbelow(999_900) + 100


def _default_stg_id() -> int:
    """Generate a positive strategy ID (1..99999)."""
    return secrets.randbelow(99_999) + 1


class OrderService:
    """Coordinates validated place/modify/cancel operations with an internal `ID` (`client_id`)."""

    def __init__(
        self,
        store: OrderBookFileStore,
        *,
        client_id: str,
        uniq_no_generator: Callable[[], int] = _default_uniq_no,
        stg_id_generator: Callable[[], int] = _default_stg_id,
    ) -> None:
        self.store = store
        self._client_id = client_id.strip()
        self._uniq_no_generator = uniq_no_generator
        self._stg_id_generator = stg_id_generator

    def _require_internal_client_id(self) -> str:
        if not self._client_id:
            raise OrderForbiddenError("Internal server client_id is not configured")
        return self._client_id

    def _assert_owned_by_internal_client(self, record: OrderRecord) -> None:
        if record.client_id != self._require_internal_client_id():
            raise OrderForbiddenError("Order is not accessible on this server instance")

    def place_order(self, request: OrderCreateRequest) -> OrderRecord:
        """Validate uniqueness, inject internal `ID`, and append an `ORDER_TYPE='L'` row."""
        internal_client_id = self._require_internal_client_id()

        def _build(existing: list[OrderRecord]) -> list[OrderRecord]:
            used_uniq_nos = {row.uniq_no for row in existing}
            record = self._to_place_record(
                request,
                client_id=internal_client_id,
                used_uniq_nos=used_uniq_nos,
                fallback_stg_id=None,
            )
            return [record]

        written = self.store.transact_append(_build)
        return written[0]

    def place_orders_batch(self, request: OrderBatchCreateRequest) -> list[OrderRecord]:
        """Validate all legs atomically, inject internal `ID`, and append together."""
        internal_client_id = self._require_internal_client_id()

        def _build(existing: list[OrderRecord]) -> list[OrderRecord]:
            used_uniq_nos = {row.uniq_no for row in existing}
            shared_stg_id = request.stg_id
            if shared_stg_id is None and any(leg.stg_id is None for leg in request.orders):
                shared_stg_id = self._stg_id_generator()

            records: list[OrderRecord] = []
            for leg in request.orders:
                record = self._to_place_record(
                    leg,
                    client_id=internal_client_id,
                    used_uniq_nos=used_uniq_nos,
                    fallback_stg_id=shared_stg_id,
                )
                used_uniq_nos.add(record.uniq_no)
                records.append(record)
            return records

        return self.store.transact_append(_build)

    def modify_order(self, uniq_no: int, request: OrderModifyRequest) -> OrderRecord:
        """Validate that `uniq_no` exists and is active, then append an `ORDER_TYPE='M'` row."""

        def _build(existing: list[OrderRecord]) -> list[OrderRecord]:
            latest = self._find_latest_by_uniq_no(existing, uniq_no)
            self._assert_owned_by_internal_client(latest)
            if latest.order_type is OrderType.CANCEL:
                raise OrderAlreadyCancelledError(
                    f"Order uniq_no={uniq_no} is already cancelled and cannot be modified"
                )

            new_lot = request.lot if request.lot is not None else latest.lot
            new_note = request.note if request.note is not None else latest.note
            new_price_type = (
                request.price_type if request.price_type is not None else latest.price_type
            )
            if request.price is not None:
                new_price = request.price
            elif new_price_type is PriceType.MARKET:
                new_price = Decimal("0")
            else:
                new_price = latest.price

            if new_price_type is PriceType.LIMIT and new_price <= 0:
                raise OrderValidationError("price must be greater than 0 for LIMIT orders")
            if new_price_type is PriceType.MARKET and new_price != 0:
                raise OrderValidationError("price must be 0 for MARKET orders")

            modified = OrderRecord(
                uniq_no=latest.uniq_no,
                contract=latest.contract,
                side=latest.side,
                lot=new_lot,
                price=new_price,
                order_type=OrderType.MODIFY,
                client_id=latest.client_id,
                stg_id=latest.stg_id,
                note=new_note,
            )
            return [modified]

        written = self.store.transact_append(_build)
        return written[0]

    def cancel_order(self, uniq_no: int) -> OrderRecord:
        """Validate that `uniq_no` exists and is active, then append an `ORDER_TYPE='C'` row."""

        def _build(existing: list[OrderRecord]) -> list[OrderRecord]:
            latest = self._find_latest_by_uniq_no(existing, uniq_no)
            self._assert_owned_by_internal_client(latest)
            if latest.order_type is OrderType.CANCEL:
                raise OrderAlreadyCancelledError(
                    f"Order uniq_no={uniq_no} is already cancelled"
                )

            cancelled = OrderRecord(
                uniq_no=latest.uniq_no,
                contract=latest.contract,
                side=latest.side,
                lot=latest.lot,
                price=latest.price,
                order_type=OrderType.CANCEL,
                client_id=latest.client_id,
                stg_id=latest.stg_id,
                note=latest.note,
            )
            return [cancelled]

        written = self.store.transact_append(_build)
        return written[0]

    def get_order(self, uniq_no: int) -> OrderRecord:
        """Return the latest recorded state for `uniq_no`, or raise `OrderNotFoundError`."""
        existing = self.store.read_all()
        latest = self._find_latest_by_uniq_no(existing, uniq_no)
        self._assert_owned_by_internal_client(latest)
        return latest

    def list_orders(
        self,
        *,
        stg_id: int | None = None,
        side: OrderSide | None = None,
        order_type: OrderType | None = None,
        limit: int | None = None,
    ) -> list[OrderRecord]:
        """Read stored order rows belonging to the configured internal `client_id`."""
        internal_client_id = self._require_internal_client_id()
        orders = [o for o in self.store.read_all() if o.client_id == internal_client_id]

        if stg_id is not None:
            orders = [o for o in orders if o.stg_id == stg_id]
        if side is not None:
            orders = [o for o in orders if o.side is side]
        if order_type is not None:
            orders = [o for o in orders if o.order_type is order_type]
        if limit is not None:
            orders = orders[:limit]

        return orders

    def _find_latest_by_uniq_no(
        self,
        records: list[OrderRecord],
        uniq_no: int,
    ) -> OrderRecord:
        for record in reversed(records):
            if record.uniq_no == uniq_no:
                return record
        raise OrderNotFoundError(f"Order with uniq_no={uniq_no} not found")

    def _generate_unique_uniq_no(self, used_uniq_nos: set[int]) -> int:
        for _ in range(100):
            candidate = self._uniq_no_generator()
            if candidate not in used_uniq_nos:
                return candidate
        raise DuplicateOrderError("Unable to generate a unique uniq_no")

    def _to_place_record(
        self,
        request: OrderCreateRequest,
        *,
        client_id: str,
        used_uniq_nos: set[int],
        fallback_stg_id: int | None,
    ) -> OrderRecord:
        if request.uniq_no is not None:
            if request.uniq_no in used_uniq_nos:
                raise DuplicateOrderError(f"Order with uniq_no={request.uniq_no} already exists")
            uniq_no = request.uniq_no
        else:
            uniq_no = self._generate_unique_uniq_no(used_uniq_nos)

        stg_id = (
            request.stg_id
            if request.stg_id is not None
            else (
                fallback_stg_id
                if fallback_stg_id is not None
                else self._stg_id_generator()
            )
        )
        return OrderRecord(
            uniq_no=uniq_no,
            contract=request.contract,
            side=request.side,
            lot=request.lot,
            price=request.price,
            order_type=request.price_type.txt_order_type,
            client_id=client_id,
            stg_id=stg_id,
            note=request.note,
        )

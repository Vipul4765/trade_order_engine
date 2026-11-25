"""Order model aligned with the exact 9-column headerless OrderBook `.txt` format."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trade_order_engine.enums.book import OrderBookColumn
from trade_order_engine.enums.order import OrderSide, OrderType, PriceType
from trade_order_engine.models.contract import Contract

_EXPECTED_FIELD_COUNT = len(OrderBookColumn.row_columns())


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """Immutable representation of a single 9-field OrderBook `.txt` row.

    Column order:
        UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE

    Examples (ORDER_TYPE is always 'L'):
        Market place: 676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55
        Limit place:  677,NIFTY2690823850CE,2,5,275.55,L,CLIENT01,763,
        Modify:       677,NIFTY2690823850CE,2,5,276.25,L,CLIENT01,763,
        Cancel:       677,NIFTY2690823850CE,1,5,276.25,L,CLIENT01,763,
    """

    uniq_no: int
    contract: str
    side: OrderSide
    lot: int
    price: Decimal
    order_type: OrderType
    client_id: str
    stg_id: int
    note: str = ""

    def __post_init__(self) -> None:
        if not self.contract or not self.contract.strip():
            raise ValueError("contract must be non-empty")
        if any(ch in self.contract for ch in (",", "\n", "\r")):
            raise ValueError(f"contract contains invalid delimiter characters: {self.contract!r}")
        if not self.client_id or not self.client_id.strip():
            raise ValueError("client_id must be non-empty")
        if any(ch in self.client_id for ch in (",", "\n", "\r")):
            raise ValueError(f"client_id contains invalid delimiter characters: {self.client_id!r}")
        if any(ch in self.note for ch in (",", "\n", "\r")):
            raise ValueError(f"note contains invalid delimiter characters: {self.note!r}")
        if self.uniq_no <= 0:
            raise ValueError(f"uniq_no must be positive, got {self.uniq_no}")
        if self.stg_id <= 0:
            raise ValueError(f"stg_id must be positive, got {self.stg_id}")
        if self.lot <= 0:
            raise ValueError(f"lot must be positive, got {self.lot}")
        if not self.price.is_finite():
            raise ValueError(f"price must be finite, got {self.price}")
        if self.price < 0:
            raise ValueError(f"price cannot be negative, got {self.price}")

    @property
    def signed_lot(self) -> int:
        """Signed lot size (+lot for BUY, -lot for SELL)."""
        return self.lot * self.side.sign

    @property
    def price_type(self) -> PriceType:
        """Derived pricing mode: `MARKET` when `price == 0`, else `LIMIT`."""
        return PriceType.MARKET if self.price == 0 else PriceType.LIMIT

    @property
    def parsed_contract(self) -> Contract:
        """Parse `contract` into a structured `Contract` instance."""
        return Contract.parse(self.contract)

    def to_csv_line(self) -> str:
        """Serialize this order to the exact 9-field `.txt` row."""
        return (
            f"{self.uniq_no},{self.contract},{int(self.side)},{self.lot},"
            f"{format(self.price, 'f')},{self.order_type.value},{self.client_id},"
            f"{self.stg_id},{self.note}"
        )

    @classmethod
    def from_row(cls, fields: Sequence[str]) -> OrderRecord:
        """Build an `OrderRecord` from 9 positional string fields."""
        if len(fields) != _EXPECTED_FIELD_COUNT:
            raise ValueError(
                f"Expected {_EXPECTED_FIELD_COUNT} fields, got {len(fields)}: {list(fields)!r}"
            )

        (
            raw_uniq_no,
            raw_contract,
            raw_side,
            raw_lot,
            raw_price,
            raw_order_type,
            raw_client_id,
            raw_stg_id,
            raw_note,
        ) = (field.strip() for field in fields)

        try:
            price = Decimal(raw_price)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid price value: {raw_price!r}") from exc

        return cls(
            uniq_no=int(raw_uniq_no),
            contract=raw_contract,
            side=OrderSide.from_raw(raw_side),
            lot=int(raw_lot),
            price=price,
            order_type=OrderType.from_raw(raw_order_type),
            client_id=raw_client_id,
            stg_id=int(raw_stg_id),
            note=raw_note,
        )

    @classmethod
    def from_csv_line(cls, line: str) -> OrderRecord:
        """Build an `OrderRecord` from a raw comma-separated OrderBook `.txt` line."""
        return cls.from_row(line.rstrip("\r\n").split(","))

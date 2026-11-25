"""Order-domain enumerations mapped from the 9-column OrderBook `.txt` format."""

from __future__ import annotations

from enum import Enum, IntEnum


class OrderSide(IntEnum):
    """Trade direction from the `BUY/SELL` column (`1` = BUY, `2` = SELL)."""

    BUY = 1
    SELL = 2

    @property
    def sign(self) -> int:
        """Signed multiplier (+1 for BUY, -1 for SELL) for position/risk math."""
        return 1 if self is OrderSide.BUY else -1

    @classmethod
    def from_raw(cls, value: int | str | OrderSide) -> OrderSide:
        """Parse raw numeric or string side codes into `OrderSide`."""
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            raise ValueError(f"Invalid OrderSide value: {value!r}")
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"1", "B", "BUY"}:
                return cls.BUY
            if normalized in {"2", "S", "SELL"}:
                return cls.SELL
        raise ValueError(f"Invalid OrderSide value: {value!r}")


class OrderType(str, Enum):
    """Action code written to the `ORDER_TYPE` column (column 6) in `.txt`.

    - `L` (`PLACE`): Place order (used for BOTH Limit with `PRICE > 0` and Market with `PRICE = 0`)
    - `M` (`MODIFY`): Modify an active order
    - `C` (`CANCEL`): Cancel an active order
    """

    PLACE = "L"
    MODIFY = "M"
    CANCEL = "C"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_raw(cls, value: str | OrderType) -> OrderType:
        """Parse raw action codes (`L`/`PLACE`, `M`/`MODIFY`, `C`/`CANCEL`) into `OrderType`."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            aliases = {
                "L": cls.PLACE,
                "PLACE": cls.PLACE,
                "M": cls.MODIFY,
                "MOD": cls.MODIFY,
                "MODIFY": cls.MODIFY,
                "C": cls.CANCEL,
                "CAN": cls.CANCEL,
                "CANCEL": cls.CANCEL,
            }
            if normalized in aliases:
                return aliases[normalized]
        raise ValueError(f"Invalid OrderType value: {value!r}")


class PriceType(str, Enum):
    """Order execution pricing mode (`LIMIT`: `PRICE > 0`, `MARKET`: `PRICE = 0`).

    In the `.txt` OrderBook file, both `LIMIT` and `MARKET` place orders write
    `ORDER_TYPE = "L"`, distinguished by `PRICE > 0` vs `PRICE = 0`.
    """

    LIMIT = "LIMIT"
    MARKET = "MARKET"

    def __str__(self) -> str:
        return self.value

    @property
    def txt_order_type(self) -> OrderType:
        """`ORDER_TYPE` wire code for placing Limit or Market orders (always `'L'`)."""
        return OrderType.PLACE

    @classmethod
    def from_raw(cls, value: str | PriceType) -> PriceType:
        """Parse pricing mode codes (`LIMIT`/`L`, `MARKET`/`M`/`MKT`) into `PriceType`."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            aliases = {
                "L": cls.LIMIT,
                "LIMIT": cls.LIMIT,
                "M": cls.MARKET,
                "MKT": cls.MARKET,
                "MARKET": cls.MARKET,
            }
            if normalized in aliases:
                return aliases[normalized]
        raise ValueError(f"Invalid PriceType value: {value!r}")

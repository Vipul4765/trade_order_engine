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

    @property
    def opposite(self) -> OrderSide:
        """Return the opposite side (`BUY -> SELL`, `SELL -> BUY`) used on cancel."""
        return OrderSide.SELL if self is OrderSide.BUY else OrderSide.BUY

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
    """Wire code written to the `ORDER_TYPE` column (column 6) in `.txt` — always `'L'`."""

    LIMIT = "L"
    L = "L"  # Alias

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_raw(cls, value: str | OrderType) -> OrderType:
        """Parse the `ORDER_TYPE` column (`'L'` / `'LIMIT'`)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"L", "LIMIT"}:
                return cls.LIMIT
        raise ValueError(f"Invalid OrderType value (only 'L' is allowed): {value!r}")


class OrderAction(str, Enum):
    """Lifecycle action of an order row (while `.txt` `ORDER_TYPE` stays `'L'`).

    - `PLACE`: initial order row
    - `MODIFY`: subsequent row with the same `UNIQ NO` and same `BUY/SELL` side
    - `CANCEL`: subsequent row with the same `UNIQ NO` and flipped `BUY/SELL` side (`1 <-> 2`)
    """

    PLACE = "PLACE"
    MODIFY = "MODIFY"
    CANCEL = "CANCEL"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_raw(cls, value: str | OrderAction) -> OrderAction:
        """Parse action filter strings (`PLACE`, `MODIFY`, `CANCEL`)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in cls.__members__:
                return cls[normalized]
        raise ValueError(f"Invalid OrderAction value: {value!r}")


class PriceType(str, Enum):
    """Order execution pricing mode (`LIMIT`: `PRICE > 0`, `MARKET`: `PRICE = 0`).

    In the `.txt` OrderBook file, `ORDER_TYPE` is always `'L'` for both
    `LIMIT` (`PRICE > 0`) and `MARKET` (`PRICE = 0`).
    """

    LIMIT = "LIMIT"
    MARKET = "MARKET"

    def __str__(self) -> str:
        return self.value

    @property
    def txt_order_type(self) -> OrderType:
        """`ORDER_TYPE` wire code written to `.txt` (always `'L'`)."""
        return OrderType.LIMIT

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

"""Book-type and 9-column OrderBook `.txt` schema enumerations."""

from __future__ import annotations

from enum import Enum


class BookType(str, Enum):
    """Supported broker book file types (`OrderBook` and `TradeBook`)."""

    ORDER_BOOK = "OrderBook"
    TRADE_BOOK = "TradeBook"

    def __str__(self) -> str:
        return self.value


class OrderBookColumn(str, Enum):
    """Ordered 9-column schema for headerless OrderBook `.txt` rows:

    `UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE`
    """

    UNIQ_NO = "UNIQ NO"
    CONTRACT = "CONTRACT"
    BUY_SELL = "BUY/SELL"
    LOT = "LOT"
    PRICE = "PRICE"
    ORDER_TYPE = "ORDER_TYPE"
    ID = "ID"
    STG_ID = "STG_ID"
    NOTE = "NOTE"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def row_columns(cls) -> tuple[OrderBookColumn, ...]:
        """All 9 columns in exact positional order."""
        return tuple(cls)

"""Unit tests for all domain enums."""

from __future__ import annotations

import pytest

from trade_order_engine import (
    BookType,
    InstrumentType,
    OptionType,
    OrderAction,
    OrderBookColumn,
    OrderSide,
    OrderType,
    PriceType,
    Underlying,
)


class TestOrderSide:
    def test_values_sign_and_opposite(self) -> None:
        assert OrderSide.BUY == 1
        assert OrderSide.SELL == 2
        assert OrderSide.BUY.sign == 1
        assert OrderSide.SELL.sign == -1
        assert OrderSide.BUY.opposite is OrderSide.SELL
        assert OrderSide.SELL.opposite is OrderSide.BUY

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (1, OrderSide.BUY),
            ("1", OrderSide.BUY),
            (" 1 ", OrderSide.BUY),
            ("buy", OrderSide.BUY),
            ("B", OrderSide.BUY),
            (2, OrderSide.SELL),
            ("2", OrderSide.SELL),
            ("SELL", OrderSide.SELL),
            ("s", OrderSide.SELL),
            (OrderSide.BUY, OrderSide.BUY),
        ],
    )
    def test_from_raw_valid(self, raw: int | str | OrderSide, expected: OrderSide) -> None:
        assert OrderSide.from_raw(raw) is expected

    @pytest.mark.parametrize("raw", [0, 3, "0", "3", "HOLD", "", True, False])
    def test_from_raw_invalid(self, raw: object) -> None:
        with pytest.raises(ValueError):
            OrderSide.from_raw(raw)  # type: ignore[arg-type]


class TestOrderTypeAndAction:
    def test_order_type_is_always_L(self) -> None:
        assert tuple(OrderType) == (OrderType.LIMIT,)
        assert OrderType.LIMIT == "L"
        assert OrderType.L is OrderType.LIMIT
        assert str(OrderType.LIMIT) == "L"
        assert OrderType.from_raw("l") is OrderType.LIMIT
        assert OrderType.from_raw("LIMIT") is OrderType.LIMIT

    @pytest.mark.parametrize("raw", ["M", "C", "SL", "SLM", "0", "", 0])
    def test_order_type_rejects_non_L(self, raw: object) -> None:
        with pytest.raises(ValueError):
            OrderType.from_raw(raw)  # type: ignore[arg-type]

    def test_order_action_parsing(self) -> None:
        assert tuple(OrderAction) == (OrderAction.PLACE, OrderAction.MODIFY, OrderAction.CANCEL)
        assert OrderAction.from_raw("place") is OrderAction.PLACE
        assert OrderAction.from_raw("MODIFY") is OrderAction.MODIFY
        assert OrderAction.from_raw("cancel") is OrderAction.CANCEL
        with pytest.raises(ValueError):
            OrderAction.from_raw("UNKNOWN")


class TestPriceType:
    def test_values_and_txt_order_type(self) -> None:
        assert tuple(PriceType) == (PriceType.LIMIT, PriceType.MARKET)
        assert PriceType.LIMIT == "LIMIT"
        assert PriceType.MARKET == "MARKET"
        assert PriceType.LIMIT.txt_order_type is OrderType.LIMIT
        assert PriceType.MARKET.txt_order_type is OrderType.LIMIT
        assert str(PriceType.LIMIT.txt_order_type) == "L"
        assert str(PriceType.MARKET.txt_order_type) == "L"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("L", PriceType.LIMIT),
            ("limit", PriceType.LIMIT),
            (" M ", PriceType.MARKET),
            ("mkt", PriceType.MARKET),
            ("market", PriceType.MARKET),
            (PriceType.LIMIT, PriceType.LIMIT),
        ],
    )
    def test_from_raw_valid(self, raw: str | PriceType, expected: PriceType) -> None:
        assert PriceType.from_raw(raw) is expected

    @pytest.mark.parametrize("raw", ["", "X", "SL", "SLM", "IOC", 0])
    def test_from_raw_invalid(self, raw: object) -> None:
        with pytest.raises(ValueError):
            PriceType.from_raw(raw)  # type: ignore[arg-type]


class TestInstrumentAndBookEnums:
    def test_option_type_aliases_and_parsing(self) -> None:
        assert OptionType.CALL is OptionType.CE
        assert OptionType.PUT is OptionType.PE
        assert str(OptionType.CE) == "CE"
        assert str(OptionType.PE) == "PE"
        assert OptionType.from_raw("ce") is OptionType.CALL
        assert OptionType.from_raw("PUT") is OptionType.PUT
        with pytest.raises(ValueError):
            OptionType.from_raw("FUT")

    def test_instrument_and_underlying(self) -> None:
        assert str(InstrumentType.OPTION) == "OPT"
        assert str(Underlying.NIFTY) == "NIFTY"
        assert str(BookType.ORDER_BOOK) == "OrderBook"
        assert str(BookType.TRADE_BOOK) == "TradeBook"

    def test_order_book_columns_exact_9_field_schema(self) -> None:
        row_cols = OrderBookColumn.row_columns()
        assert len(row_cols) == 9
        assert [str(c) for c in row_cols] == [
            "UNIQ NO",
            "CONTRACT",
            "BUY/SELL",
            "LOT",
            "PRICE",
            "ORDER_TYPE",
            "ID",
            "STG_ID",
            "NOTE",
        ]

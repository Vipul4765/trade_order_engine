"""Unit tests for Contract and 9-column OrderRecord models."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trade_order_engine import (
    Contract,
    InstrumentType,
    OptionType,
    OrderRecord,
    OrderSide,
    OrderType,
    PriceType,
    Underlying,
)


class TestContract:
    def test_parse_weekly_nifty_ce_and_pe(self) -> None:
        ce = Contract.parse("NIFTY2690823850CE")
        assert ce.raw == "NIFTY2690823850CE"
        assert ce.underlying == "NIFTY"
        assert ce.known_underlying is Underlying.NIFTY
        assert ce.expiry_code == "26908"
        assert ce.strike == Decimal("23850")
        assert ce.option_type is OptionType.CE
        assert ce.instrument_type is InstrumentType.OPTION

        pe = Contract.parse("NIFTY2690823900PE")
        assert pe.strike == Decimal("23900")
        assert pe.option_type is OptionType.PE

    def test_parse_monthly_and_october_weekly_formats(self) -> None:
        monthly = Contract.parse("BANKNIFTY26SEP52000PE")
        assert monthly.underlying == "BANKNIFTY"
        assert monthly.known_underlying is Underlying.BANKNIFTY
        assert monthly.expiry_code == "26SEP"
        assert monthly.strike == Decimal("52000")
        assert monthly.option_type is OptionType.PUT

        oct_weekly = Contract.parse("MIDCPNIFTY26O1512500CE")
        assert oct_weekly.underlying == "MIDCPNIFTY"
        assert oct_weekly.expiry_code == "26O15"
        assert oct_weekly.strike == Decimal("12500")

    def test_parse_unknown_underlying_still_supported(self) -> None:
        stock_opt = Contract.parse("RELIANCE269081400CE")
        assert stock_opt.underlying == "RELIANCE"
        assert stock_opt.known_underlying is None
        assert stock_opt.strike == Decimal("1400")

    @pytest.mark.parametrize("bad_symbol", ["", "NIFTY", "NIFTY2690823850FUT", "12345CE"])
    def test_parse_invalid_contract(self, bad_symbol: str) -> None:
        with pytest.raises(ValueError):
            Contract.parse(bad_symbol)


class TestOrderRecord:
    @pytest.mark.parametrize(
        (
            "line",
            "expected_side",
            "expected_signed_lot",
            "expected_price",
            "expected_price_type",
            "expected_order_type",
            "expected_client",
            "expected_stg_id",
            "expected_note",
        ),
        [
            (
                "676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55",
                OrderSide.SELL,
                -5,
                Decimal("0"),
                PriceType.MARKET,
                OrderType.PLACE,
                "CLIENT01",
                763,
                "275.55",
            ),
            (
                "47715,NIFTY2690823850CE,2,5,275.45,L,CLIENT02,229,",
                OrderSide.SELL,
                -5,
                Decimal("275.45"),
                PriceType.LIMIT,
                OrderType.PLACE,
                "CLIENT02",
                229,
                "",
            ),
            (
                "785,NIFTY2690823850CE,1,10,277.05,M,CLIENT01,763,reprice",
                OrderSide.BUY,
                10,
                Decimal("277.05"),
                PriceType.LIMIT,
                OrderType.MODIFY,
                "CLIENT01",
                763,
                "reprice",
            ),
            (
                "8790,NIFTY2690823850CE,2,1,0,C,CLIENT03,421,cancel-leg",
                OrderSide.SELL,
                -1,
                Decimal("0"),
                PriceType.MARKET,
                OrderType.CANCEL,
                "CLIENT03",
                421,
                "cancel-leg",
            ),
        ],
    )
    def test_from_csv_line_and_round_trip(
        self,
        line: str,
        expected_side: OrderSide,
        expected_signed_lot: int,
        expected_price: Decimal,
        expected_price_type: PriceType,
        expected_order_type: OrderType,
        expected_client: str,
        expected_stg_id: int,
        expected_note: str,
    ) -> None:
        order = OrderRecord.from_csv_line(line)

        assert order.side is expected_side
        assert order.signed_lot == expected_signed_lot
        assert order.price == expected_price
        assert order.price_type is expected_price_type
        assert order.order_type is expected_order_type
        assert order.client_id == expected_client
        assert order.stg_id == expected_stg_id
        assert order.note == expected_note
        assert order.parsed_contract.underlying == "NIFTY"
        assert order.to_csv_line() == line

    def test_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="Expected 9 fields"):
            OrderRecord.from_csv_line("676,NIFTY2690823850CE,2,5,0,L,763,275.55")

        with pytest.raises(ValueError, match="lot must be positive"):
            OrderRecord.from_csv_line("676,NIFTY2690823850CE,2,0,0,L,CLIENT01,763,275.55")

        with pytest.raises(ValueError, match="price cannot be negative"):
            OrderRecord.from_csv_line("676,NIFTY2690823850CE,2,5,-1.0,L,CLIENT01,763,")

        with pytest.raises(ValueError, match="Invalid OrderType"):
            OrderRecord.from_csv_line("676,NIFTY2690823850CE,2,5,0,X,CLIENT01,763,")

        with pytest.raises(ValueError, match="note contains invalid delimiter"):
            OrderRecord(
                uniq_no=676,
                contract="NIFTY2690823850CE",
                side=OrderSide.SELL,
                lot=5,
                price=Decimal("0"),
                order_type=OrderType.PLACE,
                client_id="CLIENT01",
                stg_id=763,
                note="bad,note",
            )

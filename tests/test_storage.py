"""Unit tests for headerless `.txt` OrderBook file storage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from trade_order_engine import (
    ORDERBOOK_SCHEMA_HEADER,
    OrderBookFileStore,
    OrderRecord,
    OrderSide,
    OrderType,
)


def _sample_order(
    uniq_no: int = 676,
    stg_id: int = 763,
    side: OrderSide = OrderSide.SELL,
    price: Decimal = Decimal("0"),
    note: str = "275.55",
) -> OrderRecord:
    return OrderRecord(
        uniq_no=uniq_no,
        contract="NIFTY2690823850CE",
        side=side,
        lot=5,
        price=price,
        order_type=OrderType.LIMIT,
        client_id="CLIENT01",
        stg_id=stg_id,
        note=note,
    )


class TestOrderBookFileStore:
    def test_writes_headerless_9_field_rows(self, tmp_path: Path) -> None:
        file_path = tmp_path / "nested" / "OrderBook.txt"
        store = OrderBookFileStore(file_path)

        written_line = store.append(_sample_order())
        assert written_line == "676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55"

        # No header line written — data rows only
        lines = file_path.read_text(encoding="utf-8").splitlines()
        assert lines == [
            "676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55",
        ]

        records = store.read_all()
        assert len(records) == 1
        assert records[0] == _sample_order()

    def test_appends_cleanly_when_existing_file_lacks_trailing_newline(self, tmp_path: Path) -> None:
        file_path = tmp_path / "OrderBook.txt"
        file_path.write_text(
            "676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55",
            encoding="utf-8",
        )
        store = OrderBookFileStore(file_path)

        pe_leg = OrderRecord(
            uniq_no=114,
            contract="NIFTY2690823850PE",
            side=OrderSide.SELL,
            lot=5,
            price=Decimal("275.55"),
            order_type=OrderType.LIMIT,
            client_id="CLIENT01",
            stg_id=763,
            note="",
        )
        store.append(pe_leg)

        lines = file_path.read_text(encoding="utf-8").splitlines()
        assert lines == [
            "676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55",
            "114,NIFTY2690823850PE,2,5,275.55,L,CLIENT01,763,",
        ]

    def test_read_all_skips_optional_header_if_present_and_handles_missing_file(
        self,
        tmp_path: Path,
    ) -> None:
        missing = OrderBookFileStore(tmp_path / "does_not_exist.txt")
        assert missing.read_all() == []

        with_header = tmp_path / "with_header.txt"
        with_header.write_text(
            f"{ORDERBOOK_SCHEMA_HEADER}\n676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55\n",
            encoding="utf-8",
        )
        records = OrderBookFileStore(with_header).read_all()
        assert len(records) == 1
        assert records[0].uniq_no == 676

    def test_concurrent_appends_preserve_all_rows(self, tmp_path: Path) -> None:
        store = OrderBookFileStore(tmp_path / "OrderBook.txt")

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(store.append, _sample_order(uniq_no=1000 + i)) for i in range(40)]
            for future in futures:
                future.result()

        records = store.read_all()
        assert len(records) == 40
        assert {r.uniq_no for r in records} == {1000 + i for i in range(40)}

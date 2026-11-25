"""Thread-safe and file-locked headerless `.txt` OrderBook writer and reader."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

from trade_order_engine.enums.book import OrderBookColumn
from trade_order_engine.models.order import OrderRecord

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

ORDERBOOK_SCHEMA_HEADER = ",".join(str(col) for col in OrderBookColumn.row_columns())


@contextmanager
def _locked_file(handle: IO[str], *, exclusive: bool) -> Iterator[IO[str]]:
    """Acquire an advisory POSIX file lock when available."""
    if fcntl is not None:
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), lock_mode)
    try:
        yield handle
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_content(content: str) -> list[OrderRecord]:
    records: list[OrderRecord] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == ORDERBOOK_SCHEMA_HEADER:
            continue
        records.append(OrderRecord.from_csv_line(raw_line))
    return records


class OrderBookFileStore:
    """Appends validated 9-field rows to and reads rows from a headerless `.txt` file.

    Format (data rows only, no header line written):
        UNIQ NO,CONTRACT,BUY/SELL,LOT,PRICE,ORDER_TYPE,ID,STG_ID,NOTE
        676,NIFTY2690823850CE,2,5,0,L,CLIENT01,763,275.55
    """

    def __init__(self, file_path: Path | str) -> None:
        self.file_path = Path(file_path)
        self._thread_lock = threading.Lock()

    def append(self, order: OrderRecord) -> str:
        """Append a single validated order row and return the exact line written."""
        return self.append_many([order])[0]

    def append_many(self, orders: Sequence[OrderRecord]) -> list[str]:
        """Atomically append one or more validated order rows under a single lock."""
        if not orders:
            return []

        lines = [order.to_csv_line() for order in orders]
        payload = "\n".join(lines) + "\n"

        with self._thread_lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a+", encoding="utf-8", newline="\n") as handle:
                with _locked_file(handle, exclusive=True):
                    handle.seek(0)
                    existing_content = handle.read()
                    handle.seek(0, os.SEEK_END)

                    if existing_content and not existing_content.endswith("\n"):
                        handle.write("\n")

                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            self._restrict_file_permissions()

        return lines

    def transact_append(
        self,
        builder: Callable[[list[OrderRecord]], Sequence[OrderRecord]],
    ) -> list[OrderRecord]:
        """Atomically read existing records, run `builder` to validate/build new rows, and append.

        Holds both the in-process thread lock and an exclusive POSIX file lock across the
        read-validate-write cycle so concurrent place/modify/cancel operations cannot race.
        If `builder` raises or returns an empty sequence, the file is left untouched.
        """
        with self._thread_lock:
            if not self.file_path.exists():
                new_orders = list(builder([]))
                if not new_orders:
                    return []
                lines = [order.to_csv_line() for order in new_orders]
                payload = "\n".join(lines) + "\n"

                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                with self.file_path.open("a+", encoding="utf-8", newline="\n") as handle:
                    with _locked_file(handle, exclusive=True):
                        handle.seek(0)
                        existing_content = handle.read()
                        handle.seek(0, os.SEEK_END)
                        if existing_content and not existing_content.endswith("\n"):
                            handle.write("\n")
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                self._restrict_file_permissions()
                return new_orders

            with self.file_path.open("r+", encoding="utf-8", newline="\n") as handle:
                with _locked_file(handle, exclusive=True):
                    handle.seek(0)
                    existing_content = handle.read()
                    existing_records = _parse_content(existing_content)

                    new_orders = list(builder(existing_records))
                    if not new_orders:
                        return []

                    lines = [order.to_csv_line() for order in new_orders]
                    payload = "\n".join(lines) + "\n"

                    handle.seek(0, os.SEEK_END)
                    if existing_content and not existing_content.endswith("\n"):
                        handle.write("\n")
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())

            return new_orders

    def read_all(self) -> list[OrderRecord]:
        """Read all order records currently stored in the `.txt` file."""
        if not self.file_path.exists():
            return []

        with self._thread_lock:
            with self.file_path.open("r", encoding="utf-8") as handle:
                with _locked_file(handle, exclusive=False):
                    return _parse_content(handle.read())

    def _restrict_file_permissions(self) -> None:
        """Restrict OrderBook `.txt` file permissions to owner read/write (0600)."""
        try:
            os.chmod(self.file_path, 0o600)
        except OSError:  # pragma: no cover - platform/filesystem dependent
            pass

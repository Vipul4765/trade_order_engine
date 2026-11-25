"""Parsed option contract model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from trade_order_engine.enums.instrument import InstrumentType, OptionType, Underlying

# Matches NSE/BSE option contract codes such as:
# - Weekly:  NIFTY2690823850CE  (YY + [1-9OND] + DD)
# - Monthly: NIFTY26SEP23850CE  (YY + MMM)
_OPTION_CONTRACT_RE = re.compile(
    r"^(?P<underlying>[A-Z][A-Z&-]*?)"
    r"(?P<expiry>\d{2}(?:[1-9OND]\d{2}|[A-Z]{3}))"
    r"(?P<strike>\d+(?:\.\d+)?)"
    r"(?P<option_type>CE|PE)$"
)


@dataclass(frozen=True, slots=True)
class Contract:
    """Structured representation of a derivative contract symbol."""

    raw: str
    underlying: str
    expiry_code: str
    strike: Decimal
    option_type: OptionType
    instrument_type: InstrumentType = InstrumentType.OPTION

    @property
    def known_underlying(self) -> Underlying | None:
        """Return matching `Underlying` enum member if recognized, else `None`."""
        try:
            return Underlying(self.underlying)
        except ValueError:
            return None

    @classmethod
    def parse(cls, symbol: str) -> Contract:
        """Parse a raw option contract string like `NIFTY2690823850CE`."""
        cleaned = symbol.strip().upper()
        match = _OPTION_CONTRACT_RE.match(cleaned)
        if not match:
            raise ValueError(f"Unsupported or invalid option contract symbol: {symbol!r}")

        return cls(
            raw=cleaned,
            underlying=match.group("underlying"),
            expiry_code=match.group("expiry"),
            strike=Decimal(match.group("strike")),
            option_type=OptionType.from_raw(match.group("option_type")),
            instrument_type=InstrumentType.OPTION,
        )

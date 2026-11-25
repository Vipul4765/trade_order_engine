"""Instrument and contract-component enumerations."""

from __future__ import annotations

from enum import Enum


class OptionType(str, Enum):
    """Option right parsed from contract suffixes (`CE` / `PE`)."""

    CALL = "CE"
    PUT = "PE"
    CE = "CE"  # Alias for CALL
    PE = "PE"  # Alias for PUT

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_raw(cls, value: str | OptionType) -> OptionType:
        """Parse raw option type codes (`CE`, `PE`, `CALL`, `PUT`) into `OptionType`."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            aliases = {
                "CE": cls.CALL,
                "C": cls.CALL,
                "CALL": cls.CALL,
                "PE": cls.PUT,
                "P": cls.PUT,
                "PUT": cls.PUT,
            }
            if normalized in aliases:
                return aliases[normalized]
        raise ValueError(f"Invalid OptionType value: {value!r}")


class InstrumentType(str, Enum):
    """High-level instrument classification."""

    OPTION = "OPT"
    FUTURE = "FUT"
    EQUITY = "EQ"

    def __str__(self) -> str:
        return self.value


class Underlying(str, Enum):
    """Common Indian index underlyings."""

    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    FINNIFTY = "FINNIFTY"
    MIDCPNIFTY = "MIDCPNIFTY"
    SENSEX = "SENSEX"
    BANKEX = "BANKEX"

    def __str__(self) -> str:
        return self.value

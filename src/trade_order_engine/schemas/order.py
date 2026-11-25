"""Pydantic request/response schemas and validation rules for the order API.

Note: `ID` (`client_id`) is strictly internal (injected server-side from
`ORDER_CLIENT_ID`) and is intentionally excluded from all public schemas.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from trade_order_engine.enums.order import OrderSide, OrderType, PriceType
from trade_order_engine.models.contract import Contract
from trade_order_engine.models.order import OrderRecord


def _validate_note_value(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("note must be a string")
    cleaned = value.strip()
    if any(ch in cleaned for ch in (",", "\n", "\r")):
        raise ValueError("note cannot contain commas or newline characters")
    if len(cleaned) > 128:
        raise ValueError("note cannot exceed 128 characters")
    return cleaned


class OrderCreateRequest(BaseModel):
    """Payload to validate and place a single order (`ORDER_TYPE = 'L'`) into `.txt`."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contract: str = Field(
        ...,
        validation_alias=AliasChoices("contract", "CONTRACT"),
        description="Option contract symbol, e.g. NIFTY2690823850CE",
        examples=["NIFTY2690823850CE"],
    )
    side: OrderSide = Field(
        ...,
        validation_alias=AliasChoices("side", "buy_sell", "buy/sell", "BUY/SELL"),
        description="Order side: 1 / BUY or 2 / SELL",
        examples=[2, "SELL"],
    )
    lot: int = Field(
        ...,
        gt=0,
        validation_alias=AliasChoices("lot", "LOT"),
        description="Positive number of lots",
        examples=[5],
    )
    price_type: PriceType = Field(
        default=PriceType.LIMIT,
        description="Pricing mode: LIMIT (price > 0) or MARKET (price = 0); both write ORDER_TYPE='L'",
        examples=["LIMIT", "MARKET"],
    )
    price: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        validation_alias=AliasChoices("price", "PRICE"),
        description="Order price (> 0 for LIMIT orders; must be 0 for MARKET orders)",
        examples=["275.55", "0"],
    )
    uniq_no: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("uniq_no", "UNIQ NO", "rnd_no"),
        description="Optional unique order number (auto-generated if omitted)",
        examples=[676],
    )
    stg_id: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("stg_id", "STG_ID"),
        description="Optional strategy ID (auto-generated if omitted)",
        examples=[763],
    )
    note: str = Field(
        default="",
        validation_alias=AliasChoices("note", "NOTE"),
        description="Optional order note/remark (no commas or newlines)",
        examples=["275.55"],
    )

    @field_validator("contract", mode="before")
    @classmethod
    def _validate_contract(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("contract must be a string")
        parsed = Contract.parse(value)
        return parsed.raw

    @field_validator("side", mode="before")
    @classmethod
    def _validate_side(cls, value: Any) -> OrderSide:
        return OrderSide.from_raw(value)

    @field_validator("price_type", mode="before")
    @classmethod
    def _validate_price_type(cls, value: Any) -> PriceType:
        return PriceType.from_raw(value)

    @field_validator("note", mode="before")
    @classmethod
    def _validate_note(cls, value: Any) -> str:
        if value is None:
            return ""
        return _validate_note_value(value)

    @field_validator("lot", "uniq_no", "stg_id", mode="before")
    @classmethod
    def _reject_bool_ints(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean values are not valid integers")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def _reject_bool_price(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean values are not valid prices")
        return value

    @model_validator(mode="after")
    def _validate_price_rules(self) -> OrderCreateRequest:
        if not self.price.is_finite():
            raise ValueError("price must be a finite decimal number")
        if self.price_type is PriceType.LIMIT and self.price <= 0:
            raise ValueError("price must be greater than 0 for LIMIT orders")
        if self.price_type is PriceType.MARKET and self.price != 0:
            raise ValueError("price must be 0 for MARKET orders")
        return self


class OrderBatchCreateRequest(BaseModel):
    """Payload to validate and place multiple order legs (e.g., CE + PE) atomically."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    stg_id: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("stg_id", "STG_ID"),
        description="Optional shared strategy ID applied to legs that omit stg_id",
        examples=[763],
    )
    orders: list[OrderCreateRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="One or more order legs to validate and write together",
    )

    @field_validator("stg_id", mode="before")
    @classmethod
    def _reject_bool_stg_id(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean values are not valid integers")
        return value


class OrderModifyRequest(BaseModel):
    """Payload to modify an existing active order by `uniq_no` (`ORDER_TYPE = 'M'`)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    lot: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("lot", "LOT"),
        description="Optional updated positive lot count",
        examples=[10],
    )
    price_type: PriceType | None = Field(
        default=None,
        description="Optional updated pricing mode: LIMIT (price > 0) or MARKET (price = 0)",
        examples=["LIMIT"],
    )
    price: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        validation_alias=AliasChoices("price", "PRICE"),
        description="Optional updated price (> 0 for LIMIT, must be 0 for MARKET)",
        examples=["276.10"],
    )
    note: str | None = Field(
        default=None,
        validation_alias=AliasChoices("note", "NOTE"),
        description="Optional updated note/remark",
        examples=["updated"],
    )

    @field_validator("price_type", mode="before")
    @classmethod
    def _validate_price_type(cls, value: Any) -> PriceType | None:
        if value is None:
            return None
        return PriceType.from_raw(value)

    @field_validator("note", mode="before")
    @classmethod
    def _validate_note(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _validate_note_value(value)

    @field_validator("lot", "price", mode="before")
    @classmethod
    def _reject_bool_values(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean values are not valid numeric inputs")
        return value

    @model_validator(mode="after")
    def _validate_modify_fields(self) -> OrderModifyRequest:
        if (
            self.lot is None
            and self.price is None
            and self.price_type is None
            and self.note is None
        ):
            raise ValueError(
                "At least one of 'lot', 'price', 'price_type', or 'note' must be provided"
            )
        if self.price is not None and not self.price.is_finite():
            raise ValueError("price must be a finite decimal number")
        if self.price_type is PriceType.LIMIT and self.price is not None and self.price <= 0:
            raise ValueError("price must be greater than 0 for LIMIT orders")
        if self.price_type is PriceType.MARKET and self.price is not None and self.price != 0:
            raise ValueError("price must be 0 for MARKET orders")
        return self


class OrderResponse(BaseModel):
    """Public serialized order response (internal `ID`/`client_id` is never exposed)."""

    uniq_no: int
    contract: str
    side: OrderSide
    side_name: str
    lot: int
    signed_lot: int
    price: Decimal
    price_type: PriceType
    order_type: OrderType
    order_type_name: str
    stg_id: int
    note: str

    @classmethod
    def from_record(cls, record: OrderRecord) -> OrderResponse:
        return cls(
            uniq_no=record.uniq_no,
            contract=record.contract,
            side=record.side,
            side_name=record.side.name,
            lot=record.lot,
            signed_lot=record.signed_lot,
            price=record.price,
            price_type=record.price_type,
            order_type=record.order_type,
            order_type_name=record.order_type.name,
            stg_id=record.stg_id,
            note=record.note,
        )


class OrderBatchResponse(BaseModel):
    """Response returned after validating and writing a batch of orders."""

    count: int
    orders: list[OrderResponse]


class OrderListResponse(BaseModel):
    """Response returned when reading orders back from the `.txt` OrderBook file."""

    count: int
    orders: list[OrderResponse]


class HealthResponse(BaseModel):
    """Minimal public health check response (avoids leaking internal file paths)."""

    status: str

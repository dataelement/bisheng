"""Validation and DTO schemas for unified per-tool pricing configuration."""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.domain.schemas.pricing import Currency
from bisheng.llm.domain.pricing import price_to_micro

ToolPricingMode = Literal["MONEY", "CREDITS"]

_PRICE_RE = re.compile(r"^(0|[1-9][0-9]{0,5})(\.[0-9]{1,6})?$")


class ToolPricingInput(DshContract):
    """Administrator input payload for saving one secondary tool's price."""

    pricing_mode: ToolPricingMode = "MONEY"
    currency: Currency | None = None
    price: str = Field(default="0")
    call_count: int = Field(default=1, strict=True, ge=1, le=1_000_000)
    version: int = Field(default=0, strict=True, ge=0)

    @field_validator("price", mode="before")
    @classmethod
    def normalize_price(cls, value: object) -> str:
        if value is None:
            return "0"
        text = str(value).strip()
        return "0" if not text else text

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: str) -> str:
        if not _PRICE_RE.fullmatch(value):
            raise ValueError("Price must be between 0 and 999999.999999 with at most 6 decimal places")
        return value

    @model_validator(mode="after")
    def validate_mode_currency(self):
        if self.pricing_mode == "MONEY":
            if self.currency not in ("CNY", "USD"):
                raise ValueError("Currency ('CNY' or 'USD') is required for MONEY pricing")
        else:
            self.currency = None
        return self

    @property
    def price_micro(self) -> int:
        return price_to_micro(self.price)

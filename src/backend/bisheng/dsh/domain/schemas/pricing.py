"""F015 credit settings and per-call price snapshots (integer micro-units)."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.llm.domain.pricing import MICRO, price_to_micro
from bisheng.llm.domain.pricing.schemas import Price

Currency = Literal["CNY", "USD"]
PositiveId = Annotated[int, Field(strict=True, gt=0)]

DEFAULT_CREDIT_VALUE_MICRO = 10_000  # 1 credit = 0.01 in the billing currency
# Product has not fixed the default rate yet; the prototype used 7.2.
DEFAULT_USD_CNY_RATE_MICRO = 7_200_000
CREDIT_VALUE_RANGE = (100, 100_000_000)  # 0.0001 to 100
USD_CNY_RATE_RANGE = (10_000, 100_000_000)  # 0.01 to 100


def format_micro(value: int) -> str:
    """Shortest decimal string of an integer micro-unit amount (10000 -> "0.01")."""
    text = format(Decimal(value) / MICRO, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class CreditSettingState(DshContract):
    """Effective tenant credit settings; a tenant without a row reads these defaults."""

    currency: Currency = "CNY"
    credit_value_micro: int = Field(
        default=DEFAULT_CREDIT_VALUE_MICRO, ge=CREDIT_VALUE_RANGE[0], le=CREDIT_VALUE_RANGE[1]
    )
    usd_cny_rate_micro: int = Field(
        default=DEFAULT_USD_CNY_RATE_MICRO, ge=USD_CNY_RATE_RANGE[0], le=USD_CNY_RATE_RANGE[1]
    )
    base_model_id: PositiveId | None = None
    version: int = Field(default=0, ge=0)


class CreditSettingInput(DshContract):
    version: int = Field(ge=0)
    currency: Currency
    credit_value: Price
    usd_cny_rate: Price
    base_model_id: PositiveId | None = None

    @property
    def credit_value_micro(self) -> int:
        return price_to_micro(self.credit_value)

    @property
    def usd_cny_rate_micro(self) -> int:
        return price_to_micro(self.usd_cny_rate)

    @model_validator(mode="after")
    def validate_ranges(self):
        low, high = CREDIT_VALUE_RANGE
        if not low <= self.credit_value_micro <= high:
            raise ValueError("Credit value must be between 0.0001 and 100")
        low, high = USD_CNY_RATE_RANGE
        if not low <= self.usd_cny_rate_micro <= high:
            raise ValueError("Exchange rate must be between 0.01 and 100")
        return self

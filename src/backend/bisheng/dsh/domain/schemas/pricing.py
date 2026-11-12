"""F015 credit settings and per-call price snapshots (integer micro-units)."""

from decimal import Decimal
from typing import Annotated, Literal, NamedTuple

from pydantic import Field, model_serializer, model_validator

from bisheng.dsh.domain.schemas.contracts import DshContract, DshTokenUsage
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


# Converted per-million prices stay far below this; the bound only fences corrupt input.
MAX_PRICE_MICRO = 10**15
PriceMicro = Annotated[int, Field(strict=True, ge=0, le=MAX_PRICE_MICRO)]


class PricingSnapshot(DshContract):
    """Billing-only prices frozen when a call starts (design decisions 2 and 19).

    All prices are per million tokens in the billing currency, as integer
    micro-units. Bounds stay loose on purpose: historical events must still
    validate on replay even if the admin-facing ranges change later.
    """

    currency: Currency
    credit_value_micro: int = Field(strict=True, ge=1)
    input_micro: PriceMicro
    cache_read_micro: PriceMicro
    cache_write_micro: PriceMicro
    output_micro: PriceMicro
    usd_cny_rate_micro: int | None = Field(default=None, strict=True, ge=1)  # only when a conversion happened

    @model_serializer(mode="wrap")
    def _omit_absent_rate(self, handler):
        # Every event JSON copy lives in Redis for 30 days; do not store a null per copy.
        data = handler(self)
        if data.get("usd_cny_rate_micro") is None:
            data.pop("usd_cny_rate_micro", None)
        return data

    @property
    def free(self) -> bool:
        return not (self.input_micro or self.cache_read_micro or self.cache_write_micro or self.output_micro)


class PriceResult(NamedTuple):
    cost_micro: int  # spend in billing-currency micro-units
    billed: int  # microcredits charged to the ledger


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def price_usage(usage: DshTokenUsage, snapshot: PricingSnapshot) -> PriceResult | None:
    """Price one call; ``None`` when usage is unknown (nothing is billed)."""
    if usage.total_tokens is None:
        return None
    read = usage.cache_read_tokens or 0
    write = usage.cache_creation_tokens or 0
    miss = usage.input_tokens - read - write
    if miss < 0:
        # An input that included its cached tokens cannot be smaller than them: this source
        # reported input exclusive of cache, so every reported input token is a miss (decision 16).
        miss = usage.input_tokens
    raw = (
        miss * snapshot.input_micro
        + read * snapshot.cache_read_micro
        + write * snapshot.cache_write_micro
        + usage.output_tokens * snapshot.output_micro
    )
    return PriceResult(ceil_div(raw, MICRO), ceil_div(raw, snapshot.credit_value_micro))

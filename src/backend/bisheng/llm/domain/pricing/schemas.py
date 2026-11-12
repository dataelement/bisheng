"""Per-model token prices stored in ``llm_model.config["pricing"]`` (F016).

Prices are decimal strings per million tokens in the price's own currency, so
storage never round-trips through floats. Billing converts them to integer
micro-units once, when a call starts (see ``dsh/domain/services/pricing.py``).
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MICRO = 1_000_000

# 0 to 999999.999999, at most six decimals, no sign / exponent / leading zeros.
Price = Annotated[str, Field(strict=True, pattern=r"^(0|[1-9]\d{0,5})(\.\d{1,6})?$")]
Currency = Literal["CNY", "USD"]
# CATALOG = equals the built-in catalog entry; MANUAL = edited by an admin;
# DEFAULT = no catalog match, filled with zeros (free). Decided by the server.
PricingSource = Literal["CATALOG", "MANUAL", "DEFAULT"]


def price_to_micro(value: str) -> int:
    """Exact integer micro-units of a validated price string."""
    return int(Decimal(value) * MICRO)


class ModelPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency
    input: Price
    cache_read: Price
    cache_write: Price | None = None  # None = billed at the input price
    output: Price
    source: PricingSource
    catalog_key: str | None = Field(default=None, max_length=128)
    catalog_version: str | None = Field(default=None, max_length=32)
    ref_key: str | None = Field(default=None, max_length=128)
    # Compare-and-swap token for the single price write path; bumped on each change.
    revision: int = Field(default=1, ge=1, strict=True)

    @property
    def effective_cache_write(self) -> str:
        return self.input if self.cache_write is None else self.cache_write

    @property
    def free(self) -> bool:
        return not any(
            price_to_micro(p) for p in (self.input, self.cache_read, self.effective_cache_write, self.output)
        )

"""F015 price snapshots: model price config + tenant credit settings -> integer snapshot."""

from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshModelPricingMissingError
from bisheng.dsh.domain.schemas.pricing import CreditSettingState, PricingSnapshot, ceil_div
from bisheng.llm.domain.pricing import MICRO, ModelPricing, price_to_micro


def convert_micro(value: int, source: str, target: str, usd_cny_rate_micro: int) -> int:
    """Convert a per-million price between CNY and USD, rounding up."""
    if source == target:
        return value
    if source == "USD":
        return ceil_div(value * usd_cny_rate_micro, MICRO)
    return ceil_div(value * MICRO, usd_cny_rate_micro)


def build_snapshot(pricing_config, setting: CreditSettingState) -> PricingSnapshot:
    """Freeze the prices for one call. Missing or corrupt pricing is never billed as free."""
    try:
        pricing = ModelPricing.model_validate(pricing_config)
    except ValidationError as error:
        if pricing_config is not None:
            logger.warning("DSH model pricing is invalid ({} errors); refusing to bill it", error.error_count())
        raise DshModelPricingMissingError() from error
    rate = setting.usd_cny_rate_micro

    def micro(price: str) -> int:
        return convert_micro(price_to_micro(price), pricing.currency, setting.currency, rate)

    return PricingSnapshot(
        currency=setting.currency,
        credit_value_micro=setting.credit_value_micro,
        input_micro=micro(pricing.input),
        cache_read_micro=micro(pricing.cache_read),
        cache_write_micro=micro(pricing.effective_cache_write),
        output_micro=micro(pricing.output),
        usd_cny_rate_micro=rate if pricing.currency != setting.currency else None,
    )

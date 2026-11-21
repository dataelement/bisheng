"""F016 price snapshots: model price config + tenant credit settings -> integer snapshot."""

import asyncio
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshModelPricingMissingError
from bisheng.dsh.domain.schemas.pricing import (
    CreditSettingInput,
    CreditSettingState,
    PricingSnapshot,
    ceil_div,
    format_micro,
)
from bisheng.llm.domain.pricing import MICRO, ModelPricing, price_to_micro


def convert_micro(value: int, source: str, target: str, usd_cny_rate_micro: int) -> int:
    """Convert a per-million price between CNY and USD, rounding up."""
    if source == target:
        return value
    if source == "USD":
        return ceil_div(value * usd_cny_rate_micro, MICRO)
    return ceil_div(value * MICRO, usd_cny_rate_micro)


def build_snapshot(pricing_config, setting: CreditSettingState) -> PricingSnapshot:
    """Freeze a model's prices; raises DshModelPricingMissingError when they are missing or corrupt.

    Billing goes through ``billing_snapshot``, which bills such a model as free instead.
    """
    try:
        pricing = ModelPricing.model_validate(pricing_config)
    except ValidationError as error:
        if pricing_config is not None:
            logger.warning("DSH model pricing is invalid ({} errors)", error.error_count())
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


def billing_snapshot(pricing_config, setting: CreditSettingState, *, model_id: int) -> PricingSnapshot:
    """Prices frozen for one billed call.

    A model without a usable price (the upgrade's price backfill was not run, or the record is
    damaged) is billed as free rather than refused, so an upgrade never stops conversations
    (Callum, 2026-11-17). Nothing is written back: the admin table keeps showing the price as
    missing, and the backfill script still fills it from the catalog.
    """
    try:
        return build_snapshot(pricing_config, setting)
    except DshModelPricingMissingError:
        logger.warning("DSH model {} has no usable price; billing this call as free", model_id)
        return PricingSnapshot(
            currency=setting.currency,
            credit_value_micro=setting.credit_value_micro,
            input_micro=0,
            cache_read_micro=0,
            cache_write_micro=0,
            output_micro=0,
        )


# --- Credit ratio hints (decision 8: computed by the server, fixed 3:1 input:output) ---------

RATIO_STEP = Decimal("0.01")


class HintContext(NamedTuple):
    setting: CreditSettingState
    base_model_id: int | None
    # None when the base model is missing, offline, unpriced, free, or has no input or output
    # price (cache-only prices leave the ratio's denominator at zero).
    base: PricingSnapshot | None
    base_reason: str | None = None


def blended_micro(snapshot: PricingSnapshot) -> int:
    return 3 * snapshot.input_micro + snapshot.output_micro


def format_ratio(value: int, base: int) -> str:
    ratio = Decimal(value) / Decimal(base)
    if ratio < RATIO_STEP:
        return "<0.01"
    return str(ratio.quantize(RATIO_STEP, rounding=ROUND_HALF_UP))


def pricing_hint(model_id: int, pricing_config, context: HintContext) -> dict:
    """``{"ratio", "base", "free"}`` for one model; ratio is None when it cannot be shown."""
    is_base = model_id == context.base_model_id
    try:
        snapshot = build_snapshot(pricing_config, context.setting)
    except DshModelPricingMissingError:
        return {"ratio": None, "base": is_base, "free": False}
    if snapshot.free:
        return {"ratio": None, "base": is_base, "free": True}
    if context.base is None or not blended_micro(context.base):
        return {"ratio": None, "base": is_base, "free": False}
    return {"ratio": format_ratio(blended_micro(snapshot), blended_micro(context.base)), "base": is_base, "free": False}


async def default_base_model_id() -> int | None:
    from bisheng.llm.application.model_default_read import get_model_default_read_runtime

    # This is display metadata; the base snapshot below separately checks actual
    # ownership/sharing and online state. Unused voice slots cannot block ratios.
    record = await get_model_default_read_runtime().aget_default("linsight_llm")
    value = json.loads(record.payload_json).get("chat_default_model_id")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


async def read_hint_context(setting: CreditSettingState | None = None) -> HintContext:
    from bisheng.common.errcode.dsh import DshModelNotAllowedError
    from bisheng.dsh.runtime import read_credit_setting
    from bisheng.llm.domain.services.llm import LLMService

    setting = setting or await read_credit_setting()
    base_id = setting.base_model_id or await default_base_model_id()
    base, reason = None, "base_not_configured"
    if base_id:
        try:
            model, _ = await LLMService.get_dsh_model_snapshot(base_id)
            snapshot = build_snapshot((model.config or {}).get("pricing"), setting)
            if snapshot.free or not blended_micro(snapshot):
                reason = "base_price_not_positive"
            else:
                base, reason = snapshot, None
        except DshModelNotAllowedError:
            reason = "base_model_not_allowed"
        except DshModelPricingMissingError:
            reason = "base_price_missing"
    return HintContext(setting, base_id, base, reason)


async def workbench_pricing_hints(model_ids: list[str]) -> dict[str, dict]:
    """Hints for the workbench model picker, keyed by the picker's string model ids."""
    from bisheng.dsh.runtime import read_model_pricing

    context = await read_hint_context()
    hints = {}
    for model_id in model_ids:
        try:
            numeric = int(model_id)
        except (TypeError, ValueError):
            continue
        hints[model_id] = pricing_hint(numeric, await read_model_pricing(numeric), context)
    return hints


# --- Administrator views -----------------------------------------------------------------------


async def credit_setting_transaction(callback):
    def execute():
        from bisheng.core.database import get_sync_db_session
        from bisheng.dsh.domain.repositories.credit_setting import DshCreditSettingRepository

        with get_sync_db_session() as session:
            result = callback(DshCreditSettingRepository(session))
            session.commit()
            return result

    return await asyncio.to_thread(execute)


async def credit_settings_view() -> dict:
    from bisheng.dsh.domain.repositories.credit_setting import DshCreditSettingRepository

    state = await credit_setting_transaction(lambda repo: repo.effective())
    context = await read_hint_context(state)
    return {
        **DshCreditSettingRepository.payload(state),
        "effective_base_model_id": context.base_model_id,
        "base_reason": context.base_reason,
    }


async def save_credit_settings(actor: int, value: CreditSettingInput) -> dict:
    if value.base_model_id is not None:
        from bisheng.llm.domain.services.llm import LLMService

        model, _ = await LLMService.get_dsh_model_snapshot(value.base_model_id)
        setting = CreditSettingState(
            currency=value.currency,
            usd_cny_rate_micro=value.usd_cny_rate_micro,
            credit_value_micro=value.credit_value_micro,
        )
        snapshot = build_snapshot((model.config or {}).get("pricing"), setting)
        if snapshot.free or not blended_micro(snapshot):
            from bisheng.common.errcode.dsh import DshInvalidRequestError

            raise DshInvalidRequestError()
    await credit_setting_transaction(lambda repo: repo.save(actor, value))
    return await credit_settings_view()


def effective_prices(pricing: ModelPricing, setting: CreditSettingState) -> dict:
    """Prices converted to the billing currency, as decimal strings per million tokens."""
    rate = setting.usd_cny_rate_micro

    def converted(price: str) -> str:
        return format_micro(convert_micro(price_to_micro(price), pricing.currency, setting.currency, rate))

    return {
        "currency": setting.currency,
        "input": converted(pricing.input),
        "cache_read": converted(pricing.cache_read),
        "cache_write": converted(pricing.effective_cache_write),
        "output": converted(pricing.output),
    }


async def admin_model_pricing() -> list[dict]:
    """Price summary and ratio of every online LLM model of the tenant (user-selectable table)."""
    from bisheng.common.errcode.dsh import DshModelNotAllowedError
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.llm.domain.services.llm import LLMService

    context = await read_hint_context()
    rows = []
    for model_id in await LLMService.get_dsh_model_ids():
        try:
            model, server = await LLMService.get_dsh_model_metadata_snapshot(model_id)
        except DshModelNotAllowedError:
            continue
        raw = (model.config or {}).get("pricing")
        try:
            stored = ModelPricing.model_validate(raw) if raw is not None else None
        except ValidationError:
            stored = None
        rows.append(
            {
                "model_id": model_id,
                "can_edit": server.tenant_id == get_current_tenant_id(),
                "read_only": server.tenant_id != get_current_tenant_id(),
                "source_tenant_id": server.tenant_id,
                "base_reason": context.base_reason,
                "pricing": stored.model_dump() if stored else None,
                "effective": effective_prices(stored, context.setting) if stored else None,
                "edited": bool(stored and stored.source == "MANUAL"),
                "missing": stored is None,
                "hint": pricing_hint(model_id, raw, context),
            }
        )
    return rows

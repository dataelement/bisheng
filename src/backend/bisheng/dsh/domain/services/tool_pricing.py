"""Tool pricing conversion formulas and admin read/write service."""

from typing import NamedTuple

from sqlmodel import Session

from bisheng.dsh.domain.models.tool_pricing import DshToolPricing
from bisheng.dsh.domain.repositories.credit_setting import DshCreditSettingRepository
from bisheng.dsh.domain.repositories.tool_pricing import ToolPricingRepository
from bisheng.dsh.domain.schemas.pricing import CreditSettingState, ceil_div, format_micro
from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput
from bisheng.dsh.domain.schemas.usage import ToolPricingSnapshot
from bisheng.llm.domain.pricing import MICRO


class ToolChargeResult(NamedTuple):
    billed_tokens: int
    cost_micro: int | None
    currency: str | None
    snapshot: ToolPricingSnapshot


def compute_tool_charge(
    *,
    pricing_mode: str,
    currency: str | None,
    price_micro: int,
    call_count: int,
    setting: CreditSettingState,
) -> ToolChargeResult:
    """Compute per-call microcredits and frozen snapshot using exact single-step integer ceil_div."""
    if call_count < 1:
        raise ValueError("call_count must be >= 1")
    if price_micro <= 0:
        snapshot = ToolPricingSnapshot(
            pricing_mode=pricing_mode,  # type: ignore[arg-type]
            currency=currency if pricing_mode == "MONEY" else None,  # type: ignore[arg-type]
            price_micro=0,
            call_count=call_count,
            credit_value_micro=setting.credit_value_micro,
            usd_cny_rate_micro=None,
        )
        cost = 0 if pricing_mode == "MONEY" else None
        out_currency = setting.currency if pricing_mode == "MONEY" else None
        return ToolChargeResult(billed_tokens=0, cost_micro=cost, currency=out_currency, snapshot=snapshot)

    if pricing_mode == "CREDITS":
        billed_tokens = ceil_div(price_micro, call_count)
        snapshot = ToolPricingSnapshot(
            pricing_mode="CREDITS",
            currency=None,
            price_micro=price_micro,
            call_count=call_count,
            credit_value_micro=setting.credit_value_micro,
            usd_cny_rate_micro=None,
        )
        return ToolChargeResult(billed_tokens=billed_tokens, cost_micro=None, currency=None, snapshot=snapshot)

    # MONEY mode
    src_currency = currency or setting.currency
    target_currency = setting.currency
    rate = setting.usd_cny_rate_micro
    if src_currency == target_currency:
        cost_micro = ceil_div(price_micro, call_count)
        billed_tokens = ceil_div(price_micro * MICRO, call_count * setting.credit_value_micro)
        used_rate = None
    elif src_currency == "USD" and target_currency == "CNY":
        cost_micro = ceil_div(price_micro * rate, call_count * MICRO)
        billed_tokens = ceil_div(price_micro * rate, call_count * setting.credit_value_micro)
        used_rate = rate
    else:
        # src == CNY, target == USD
        cost_micro = ceil_div(price_micro * MICRO, call_count * rate)
        billed_tokens = ceil_div(price_micro * MICRO * MICRO, call_count * rate * setting.credit_value_micro)
        used_rate = rate

    snapshot = ToolPricingSnapshot(
        pricing_mode="MONEY",
        currency=src_currency,  # type: ignore[arg-type]
        price_micro=price_micro,
        call_count=call_count,
        credit_value_micro=setting.credit_value_micro,
        usd_cny_rate_micro=used_rate,
    )
    return ToolChargeResult(
        billed_tokens=billed_tokens,
        cost_micro=cost_micro,
        currency=target_currency,
        snapshot=snapshot,
    )


def enrich_pricing_item(item: dict, setting: CreditSettingState) -> dict:
    """Attach server-computed single-call estimated credits and cost for admin listing."""
    charge = compute_tool_charge(
        pricing_mode=item["pricing_mode"],
        currency=item.get("currency"),
        price_micro=item["price_micro"],
        call_count=item["call_count"],
        setting=setting,
    )
    return {
        **item,
        "estimated_credits": format_micro(charge.billed_tokens),
        "estimated_cost": format_micro(charge.cost_micro) if charge.cost_micro is not None else None,
        "effective_currency": setting.currency,
    }


def list_tenant_tool_pricing(session: Session) -> dict:
    setting = DshCreditSettingRepository(session).effective()
    rows: list[DshToolPricing] = ToolPricingRepository(session).list_all()
    items = {
        str(row.tool_id): enrich_pricing_item(ToolPricingRepository.serialize(row, tool_id=row.tool_id), setting)
        for row in rows
    }
    return {
        "credit_setting": DshCreditSettingRepository.payload(setting),
        "items": items,
    }


def save_tenant_tool_pricing(session: Session, *, tool_id: int, actor: int, value: ToolPricingInput) -> dict:
    setting = DshCreditSettingRepository(session).effective()
    saved = ToolPricingRepository(session).save(tool_id=tool_id, actor=actor, value=value)
    return enrich_pricing_item(saved, setting)

"""Runtime per-call pricing snapshot, quota enforcement and atomic settlement for tool execution."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger
from redis.exceptions import RedisError

from bisheng.common.errcode.dsh import (
    DshMonthlyTokenLimitExceededError,
    DshQuotaUnavailableError,
    DshUserDisabledError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.dsh.domain.repositories.credit_setting import DshCreditSettingRepository
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.repositories.tool_pricing import ToolPricingRepository
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.dsh.domain.schemas.usage import ToolPricingSnapshot, ToolUsageEvent
from bisheng.dsh.domain.services import chat_credits
from bisheng.dsh.domain.services.tool_pricing import compute_tool_charge
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected


@dataclass(frozen=True)
class PreparedToolBilling:
    request_id: str
    tenant_id: int
    user_id: int
    usage_month: str
    billing_timezone: str
    tool_group_id: int
    tool_group_name: str | None
    tool_id: int
    tool_key: str
    engine: str | None
    pricing_snapshot: ToolPricingSnapshot
    billed_tokens: int
    cost_micro: int | None
    currency: str | None
    source_type: str | None
    source_id: str | None
    started_at: datetime


@contextmanager
def _session_scope():
    with get_sync_db_session() as session:
        yield session


def _load_tool_pricing_and_setting(session, *, tool_id: int) -> tuple[dict | None, CreditSettingState]:
    row = ToolPricingRepository(session).get_by_tool(tool_id)
    if row is None or row.price_micro <= 0:
        return None, DshCreditSettingRepository.state(None)
    setting = DshCreditSettingRepository(session).effective()
    return (
        {
            "pricing_mode": row.pricing_mode,
            "currency": row.currency,
            "price_micro": row.price_micro,
            "call_count": row.call_count,
        },
        setting,
    )


async def _get_quota_store():
    return (await chat_credits.get_billing_runtime()).quota


async def _read_user_monthly_limit(user_id: int) -> int | None:
    from bisheng.dsh.runtime import read_policy

    policy = await read_policy(user_id)
    return None if policy is None else policy.monthly_token_limit


def _resolve_pricing(tool_id: int) -> tuple[dict | None, CreditSettingState]:
    with _session_scope() as session:
        return _load_tool_pricing_and_setting(session, tool_id=tool_id)


def _derive_source(app_type: object, app_id: str | None) -> tuple[str | None, str | None]:
    ctx_type, ctx_id = chat_credits.current_billing_source()
    raw_app = getattr(app_type, "value", app_type)
    source_type = ctx_type or (str(raw_app) if raw_app else None)
    source_id = ctx_id or (str(app_id) if app_id else None)
    return source_type, source_id


async def prepare_tool_billing(
    *,
    tool_id: int,
    tool_key: str,
    tool_group_id: int = 0,
    tool_group_name: str | None = None,
    user_id: int,
    app_type: object = None,
    app_id: str | None = None,
    engine: str | None = None,
    mode_override: str | None = None,
    source_override: tuple[str | None, str | None] | None = None,
    open_api_unbilled_override: bool | None = None,
) -> PreparedToolBilling | None:
    """Resolve frozen price, enforce real-time quota if paid & non-task, and prepare settlement."""
    from bisheng.common.services.config_service import settings

    if not settings.credit_billing.enabled:
        return None
    unbilled = chat_credits.is_open_api_unbilled() if open_api_unbilled_override is None else open_api_unbilled_override
    if unbilled:
        return None
    tenant_id = get_current_tenant_id()
    if tenant_id is None or tenant_id < 1 or user_id is None or user_id < 1 or not tool_id or tool_id < 1:
        return None

    pricing, setting = await asyncio.to_thread(_resolve_pricing, int(tool_id))
    if pricing is None or pricing.get("price_micro", 0) <= 0:
        return None

    charge = compute_tool_charge(
        pricing_mode=pricing["pricing_mode"],
        currency=pricing.get("currency"),
        price_micro=int(pricing["price_micro"]),
        call_count=int(pricing.get("call_count", 1)),
        setting=setting,
    )
    if charge.billed_tokens <= 0:
        return None

    timezone_name = settings.dsh.billing_timezone
    started = datetime.now(UTC)
    usage_month = started.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m")
    mode = chat_credits._call_mode() if mode_override is None else mode_override
    source_type, source_id = source_override if source_override is not None else _derive_source(app_type, app_id)

    quota = await _get_quota_store()
    # Check active identity when identity repository is available; real Redis quota check follows.
    try:
        limit = await _read_user_monthly_limit(int(user_id))
    except Exception:
        limit = None
    try:
        await quota.check_tool_quota(
            tenant_id=int(tenant_id),
            user_id=int(user_id),
            usage_month=usage_month,
            monthly_token_limit=limit,
            mode=mode,
        )
    except QuotaRejected as error:
        if error.reason == "quota_exceeded":
            logger.bind(tenant_id=tenant_id, user_id=user_id, tool_id=tool_id, tool_key=tool_key).info(
                "tool_billing.quota_rejected"
            )
            raise DshMonthlyTokenLimitExceededError() from error
        if error.reason in {"user_disabled", "missing_user_ledger"}:
            # Verify whether identity is active to surface clear account/ledger errors.
            identity = await CurrentIdentityRecords().get(str(tenant_id), str(user_id))
            if not identity or not identity.active or not identity.tenant_active or not identity.natural_person:
                raise DshUserDisabledError() from error
        raise DshQuotaUnavailableError() from error

    return PreparedToolBilling(
        request_id=str(uuid4()),
        tenant_id=int(tenant_id),
        user_id=int(user_id),
        usage_month=usage_month,
        billing_timezone=timezone_name,
        tool_group_id=int(tool_group_id or 0),
        tool_group_name=tool_group_name[:256] if tool_group_name else None,
        tool_id=int(tool_id),
        tool_key=str(tool_key or f"tool_{tool_id}"),
        engine=engine[:64] if engine else None,
        pricing_snapshot=charge.snapshot,
        billed_tokens=charge.billed_tokens,
        cost_micro=charge.cost_micro,
        currency=charge.currency,
        source_type=source_type[:32] if source_type else None,
        source_id=str(source_id)[:64] if source_id else None,
        started_at=started,
    )


async def settle_tool_billing(
    prepared: PreparedToolBilling | None,
    *,
    result: Literal["success", "failed", "timeout", "cancelled"],
) -> None:
    """Record tool usage atomically in Redis ledger after execution begins."""
    if prepared is None:
        return
    event = ToolUsageEvent(
        request_id=prepared.request_id,
        tenant_id=prepared.tenant_id,
        user_id=prepared.user_id,
        usage_month=prepared.usage_month,
        billing_timezone=prepared.billing_timezone,
        tool_group_id=prepared.tool_group_id,
        tool_group_name=prepared.tool_group_name,
        tool_id=prepared.tool_id,
        tool_key=prepared.tool_key,
        engine=prepared.engine,
        pricing_snapshot=prepared.pricing_snapshot,
        billed_tokens=prepared.billed_tokens,
        cost_micro=prepared.cost_micro,
        currency=prepared.currency,
        result=result,
        source_type=prepared.source_type,
        source_id=prepared.source_id,
        started_at=prepared.started_at,
        ended_at=datetime.now(UTC),
    )
    quota = await _get_quota_store()
    # 先持久化结算事件。工作进程可以用同一请求 ID 安全重试。
    await quota.stage_tool_usage(event)
    try:
        await quota.record_tool_usage(event)
    except (QuotaRejected, RedisError):
        logger.bind(
            tenant_id=prepared.tenant_id,
            user_id=prepared.user_id,
            tool_id=prepared.tool_id,
            request_id=prepared.request_id,
        ).exception("tool_billing.settlement_queued")
        return
    logger.bind(
        tenant_id=prepared.tenant_id,
        user_id=prepared.user_id,
        tool_id=prepared.tool_id,
        billed_tokens=prepared.billed_tokens,
        result=result,
    ).info("tool_billing.recorded")

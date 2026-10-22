"""Account for every Chat agent model invocation in the shared Work ledger."""

import asyncio
from datetime import UTC, datetime
from functools import wraps
from types import SimpleNamespace
from uuid import uuid4
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

_runtimes = WeakKeyDictionary()


def governed(model) -> bool:
    from bisheng.common.services.config_service import settings

    return settings.dsh.enabled and model.app_type in {"daily_chat", "linsight"}


async def start(model):
    from bisheng.common.errcode.dsh import (
        DshModelNotAllowedError,
        DshMonthlyTokenLimitExceededError,
        DshQuotaUnavailableError,
        DshUserDisabledError,
    )
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
    from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
    from bisheng.dsh.domain.schemas.usage import UsageEvent
    from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
    from bisheng.dsh.runtime import get_model_runtime, read_policy

    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshUserDisabledError()
    identity = await CurrentIdentityRecords().get(str(tenant), str(model.user_id))
    if not identity or not identity.active or not identity.tenant_active or not identity.natural_person:
        raise DshUserDisabledError()
    policy = await read_policy(model.user_id)
    # Chat accepts string IDs; the loaded record provides the canonical ledger ID.
    model_id = model.model_info.id
    if model_id not in policy.allowed_model_ids:
        raise DshModelNotAllowedError()
    loop = asyncio.get_running_loop()
    runtime = _runtimes.setdefault(loop, SimpleNamespace(settings=settings.dsh))
    service = await get_model_runtime(runtime)
    await service.activate()
    now = datetime.now(UTC)
    request_id = str(uuid4())
    event = UsageEvent(
        request_id=request_id,
        trace_id=request_id,
        tenant_id=tenant,
        user_id=model.user_id,
        session_id=request_id,
        model_id=model_id,
        credit_rate=next(row.credit_rate for row in policy.rows if row.model_id == model_id),
        usage_month=now.astimezone(ZoneInfo(settings.dsh.billing_timezone)).strftime("%Y-%m"),
        billing_timezone=settings.dsh.billing_timezone,
        policy_version=policy.version,
        quota_epoch=policy.quota_epoch,
        event_version=1,
        status="RUNNING",
        started_at=now,
    )
    try:
        event = await service.usage.check_and_start(event, monthly_token_limit=policy.monthly_token_limit)
    except QuotaRejected as error:
        if error.reason == "quota_exceeded":
            raise DshMonthlyTokenLimitExceededError() from error
        raise DshQuotaUnavailableError() from error
    return service.model, event, SimpleNamespace(usage=DshTokenUsage(), provider_request_id=None)


def observe(execution, result):
    from bisheng.dsh.infrastructure.chat_adapter import accumulate_usage

    generations = getattr(result, "generations", None)
    message = generations[0].message if generations else getattr(result, "message", result)
    execution.usage = accumulate_usage(execution.usage, message)
    execution.provider_request_id = getattr(message, "id", None) or execution.provider_request_id


async def finish(state, succeeded: bool):
    service, event, execution = state
    await service._settle(
        event, execution, "SUCCEEDED" if succeeded else "FAILED", None if succeeded else "chat_call_interrupted"
    )


def account_async(function):
    @wraps(function)
    async def wrapped(model, *args, **kwargs):
        if not governed(model):
            return await function(model, *args, **kwargs)
        state = await start(model)
        succeeded = False
        try:
            result = await function(model, *args, **kwargs)
            observe(state[2], result)
            succeeded = True
            return result
        finally:
            await asyncio.shield(finish(state, succeeded))

    return wrapped


def account_sync(function):
    @wraps(function)
    def wrapped(model, *args, **kwargs):
        from bisheng.utils.async_utils import run_async_safe

        if not governed(model):
            return function(model, *args, **kwargs)
        state = run_async_safe(start(model))
        succeeded = False
        try:
            result = function(model, *args, **kwargs)
            observe(state[2], result)
            succeeded = True
            return result
        finally:
            run_async_safe(finish(state, succeeded))

    return wrapped


def account_async_stream(function):
    @wraps(function)
    async def wrapped(model, *args, **kwargs):
        if not governed(model):
            async for chunk in function(model, *args, **kwargs):
                yield chunk
            return
        state = await start(model)
        succeeded = False
        source = function(model, *args, **kwargs)
        try:
            async for chunk in source:
                observe(state[2], chunk)
                yield chunk
            succeeded = True
        finally:
            try:
                await source.aclose()
            finally:
                await asyncio.shield(finish(state, succeeded))

    return wrapped


def account_sync_stream(function):
    @wraps(function)
    def wrapped(model, *args, **kwargs):
        from bisheng.utils.async_utils import run_async_safe

        if not governed(model):
            yield from function(model, *args, **kwargs)
            return
        state = run_async_safe(start(model))
        succeeded = False
        source = function(model, *args, **kwargs)
        try:
            for chunk in source:
                observe(state[2], chunk)
                yield chunk
            succeeded = True
        finally:
            try:
                source.close()
            finally:
                run_async_safe(finish(state, succeeded))

    return wrapped

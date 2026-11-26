"""Account for every Chat agent model invocation in the shared Work ledger."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from types import SimpleNamespace
from uuid import uuid4
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

_runtimes = WeakKeyDictionary()

# Set once a task-mode round has passed its quota check. Calls made inside that
# round are still admitted and settled in the ledger, but skip the monthly-limit
# comparison, so an allowance that runs out mid-round never cuts the round off.
_round_admitted: ContextVar[bool] = ContextVar("dsh_round_admitted", default=False)


def governed(model) -> bool:
    from bisheng.common.services.config_service import settings

    # F016: knowledge-space Q&A (main chat and image view) is billed as well. rag_traceability
    # stays out because workflows use it too; the workbench passes daily_chat instead.
    return settings.dsh.enabled and model.app_type in {"daily_chat", "linsight", "knowledge_space"}


async def admit_round(model) -> None:
    """Check the monthly allowance once before a task-mode round starts.

    Runs the same identity, model and quota checks as a per-call admission
    without writing a ledger request, then marks the current context so the
    round's calls skip the quota comparison. Raises the same DSH errors.
    """
    if not governed(model):
        return
    await start(model, mode="probe")
    _round_admitted.set(True)


async def start(model, *, mode: str = ""):
    from bisheng.common.errcode.dsh import (
        DshModelNotAllowedError,
        DshMonthlyTokenLimitExceededError,
        DshQuotaUnavailableError,
        DshUserDisabledError,
    )
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
    from bisheng.dsh.domain.schemas.usage import UsageEvent
    from bisheng.dsh.domain.services.model_access import require_model_operator
    from bisheng.dsh.domain.services.pricing import billing_snapshot
    from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
    from bisheng.dsh.runtime import (
        get_model_runtime,
        read_credit_setting,
        read_ledger_policy,
        read_model_pricing,
        read_policy,
    )

    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshUserDisabledError()
    administrator = await require_model_operator(model.user_id)
    # Chat accepts string IDs; the loaded record provides the canonical ledger ID.
    model_id = model.model_info.id
    if administrator:
        from bisheng.llm.domain.services.llm import LLMService

        # Revalidate actual ownership/sharing and online state at invocation.
        # Super-admin qualification never grants access to a sibling's provider.
        snapshots = await LLMService.get_dsh_model_catalog_snapshots([model_id])
        if model_id not in snapshots:
            raise DshModelNotAllowedError()
        policy = await read_ledger_policy(model.user_id)
    else:
        policy = await read_policy(model.user_id)
    # Helper models chosen by administrators (traceability, image view) are not limited to the
    # user's selectable models; the user's own conversation model always is.
    if not administrator and model_id not in policy.allowed_model_ids and not getattr(model, "admin_selected", False):
        raise DshModelNotAllowedError()
    # F016: read prices fresh (never from the cached model_info) and freeze them for this call.
    # A model without a usable price is billed as free (never refused).
    pricing = billing_snapshot(await read_model_pricing(model_id), await read_credit_setting(), model_id=model_id)
    loop = asyncio.get_running_loop()
    runtime = _runtimes.setdefault(loop, SimpleNamespace(settings=settings.dsh))
    service = await get_model_runtime(runtime)
    await service.activate()
    if pricing.free or administrator:
        if mode == "probe":
            # Free/admin probes do not compare a personal allowance or write a call.
            return service.model, None, None
        # Free/admin calls are recorded under the selected tenant and real user;
        # a management operator does not consume a tenant member's allowance.
        mode = "unmetered"
    now = datetime.now(UTC)
    request_id = str(uuid4())
    event = UsageEvent(
        request_id=request_id,
        trace_id=request_id,
        tenant_id=tenant,
        user_id=model.user_id,
        session_id=request_id,
        model_id=model_id,
        pricing=pricing,
        usage_month=now.astimezone(ZoneInfo(settings.dsh.billing_timezone)).strftime("%Y-%m"),
        billing_timezone=settings.dsh.billing_timezone,
        policy_version=policy.version,
        quota_epoch=policy.quota_epoch,
        event_version=1,
        status="RUNNING",
        started_at=now,
    )
    try:
        event = await service.usage.check_and_start(event, monthly_token_limit=policy.monthly_token_limit, mode=mode)
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
    await service.settle_usage(
        event,
        execution.usage,
        "SUCCEEDED" if succeeded else "FAILED",
        None if succeeded else "chat_call_interrupted",
        provider_request_id=execution.provider_request_id,
    )


@contextmanager
def unmetered():
    """Record calls made inside without comparing them with the monthly allowance.

    For work that runs after the user already got an answer (answer traceability):
    failing it on the allowance would only break an answer that was already sent.
    A task created inside inherits the flag (asyncio copies the context).
    """
    token = _round_admitted.set(True)
    try:
        yield
    finally:
        _round_admitted.reset(token)


def _call_mode() -> str:
    return "unmetered" if _round_admitted.get() else ""


def account_async(function):
    @wraps(function)
    async def wrapped(model, *args, **kwargs):
        if not governed(model):
            return await function(model, *args, **kwargs)
        state = await start(model, mode=_call_mode())
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
        # Read the round flag here: run_async_safe may run start() on another loop.
        state = run_async_safe(start(model, mode=_call_mode()))
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
        state = await start(model, mode=_call_mode())
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
        state = run_async_safe(start(model, mode=_call_mode()))
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

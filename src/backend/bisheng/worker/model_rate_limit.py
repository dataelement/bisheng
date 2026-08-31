from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from langchain_core.messages import SystemMessage

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.llm.domain.services.aliyun_rate_limit_classifier import AliyunRateLimitClassifier
from bisheng.llm.domain.services.call_logger import ModelRateLimitDiagnostics
from bisheng.llm.domain.services.llm import LLMService
from bisheng.llm.domain.services.model_rate_limit import (
    ProbeScheduler,
    ResolvedModelConfig,
    resolve_model_config,
)
from bisheng.llm.domain.services.model_rate_limit_state import ModelRateLimitStateService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

_PROBE_DELAYS = {1: 15, 2: 30, 3: 60}


class ProbeOutcome(StrEnum):
    RECOVERED = "recovered"
    STILL_RATE_LIMITED = "still_rate_limited"
    EXHAUSTED = "exhausted"
    NON_RATE_LIMIT_ERROR = "non_rate_limit_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    STALE = "stale"
    STATE_UNAVAILABLE = "state_unavailable"


ProbeCall = Callable[[int], Awaitable[None]]
ModelResolver = Callable[[int], Awaitable[ResolvedModelConfig]]


async def invoke_minimal_model_probe(
    model_id: int,
    *,
    llm_factory: Callable[..., Awaitable[Any]] = LLMService.get_bisheng_llm,
) -> None:
    llm = await llm_factory(
        model_id=model_id,
        streaming=False,
        max_tokens=1,
        temperature=0,
        app_id=ApplicationTypeEnum.MODEL_TEST.value,
        app_name=ApplicationTypeEnum.MODEL_TEST.value,
        app_type=ApplicationTypeEnum.MODEL_TEST,
        user_id=0,
    )
    await llm.ainvoke([SystemMessage(content="Reply with one token to confirm model availability.")])


async def run_model_rate_limit_probe(
    *,
    tenant_id: int,
    model_id: int,
    probe_token: str,
    probe_attempt: int,
    state_service: Any | None = None,
    model_resolver: ModelResolver = resolve_model_config,
    probe_call: ProbeCall = invoke_minimal_model_probe,
    schedule_probe: ProbeScheduler | None = None,
    diagnostics: Any = ModelRateLimitDiagnostics,
) -> ProbeOutcome:
    state_service = state_service or ModelRateLimitStateService()
    schedule_probe = schedule_probe or enqueue_model_rate_limit_probe
    try:
        claimed_version = await state_service.begin_probe(
            tenant_id=tenant_id,
            model_id=model_id,
            probe_token=probe_token,
            probe_attempt=probe_attempt,
        )
    except Exception as exc:
        diagnostics.state_write_failed(
            tenant_id=tenant_id,
            model_id=model_id,
            operation="begin_probe",
            error_type=type(exc).__name__,
        )
        return _outcome(ProbeOutcome.STATE_UNAVAILABLE, tenant_id, model_id, probe_attempt)
    if claimed_version is None:
        return _outcome(ProbeOutcome.STALE, tenant_id, model_id, probe_attempt)

    try:
        resolved = await model_resolver(model_id)
        if not bool(getattr(resolved.model, "online", False)):
            raise LookupError("model is offline")
    except Exception:
        return _outcome(ProbeOutcome.MODEL_UNAVAILABLE, tenant_id, model_id, probe_attempt)

    try:
        await probe_call(model_id)
    except Exception as exc:
        observation = AliyunRateLimitClassifier.classify(
            model=resolved.model,
            server=resolved.server,
            exc=exc,
        )
        if observation is None:
            return _outcome(ProbeOutcome.NON_RATE_LIMIT_ERROR, tenant_id, model_id, probe_attempt)

        exhausted = probe_attempt >= max(_PROBE_DELAYS)
        try:
            transition = await state_service.record_probe_rate_limited(
                tenant_id=tenant_id,
                model_id=model_id,
                observed_version=claimed_version,
                probe_attempt=probe_attempt,
                exhausted=exhausted,
            )
        except Exception as state_exc:
            diagnostics.state_write_failed(
                tenant_id=tenant_id,
                model_id=model_id,
                operation="finish_probe_limit",
                error_type=type(state_exc).__name__,
            )
            return _outcome(ProbeOutcome.STATE_UNAVAILABLE, tenant_id, model_id, probe_attempt)
        if not transition.changed:
            return _outcome(ProbeOutcome.STALE, tenant_id, model_id, probe_attempt)

        diagnostics.rate_limit_detected(
            tenant_id=tenant_id,
            model_id=model_id,
            server_id=getattr(resolved.server, "id", None),
            entry="probe",
            provider_code=observation.provider_code,
            request_id=observation.request_id,
            masked_detail=observation.masked_detail,
            probe_attempt=probe_attempt,
        )
        if exhausted:
            return _outcome(ProbeOutcome.EXHAUSTED, tenant_id, model_id, probe_attempt)
        if transition.next_probe_token is None:
            diagnostics.state_write_failed(
                tenant_id=tenant_id,
                model_id=model_id,
                operation="finish_probe_missing_token",
                error_type="InvalidProbeTransition",
            )
            return _outcome(ProbeOutcome.STATE_UNAVAILABLE, tenant_id, model_id, probe_attempt)

        await schedule_probe(
            tenant_id=tenant_id,
            model_id=model_id,
            probe_token=transition.next_probe_token,
            probe_attempt=probe_attempt + 1,
        )
        return _outcome(ProbeOutcome.STILL_RATE_LIMITED, tenant_id, model_id, probe_attempt)

    try:
        cleared = await state_service.clear_if_version(
            tenant_id=tenant_id,
            model_id=model_id,
            observed_version=claimed_version,
        )
    except Exception as exc:
        diagnostics.state_write_failed(
            tenant_id=tenant_id,
            model_id=model_id,
            operation="clear_probe_success",
            error_type=type(exc).__name__,
        )
        return _outcome(ProbeOutcome.STATE_UNAVAILABLE, tenant_id, model_id, probe_attempt)
    if cleared:
        diagnostics.rate_limit_recovered(
            tenant_id=tenant_id,
            model_id=model_id,
            probe_attempt=probe_attempt,
            status_version=claimed_version,
        )
    result = ProbeOutcome.RECOVERED if cleared else ProbeOutcome.STALE
    return _outcome(result, tenant_id, model_id, probe_attempt)


async def enqueue_model_rate_limit_probe(
    *,
    tenant_id: int,
    model_id: int,
    probe_token: str,
    probe_attempt: int,
) -> None:
    if tenant_id <= 0:
        raise ValueError("tenant_id must be positive")
    if probe_attempt not in _PROBE_DELAYS:
        raise ValueError("probe_attempt must be between 1 and 3")
    probe_aliyun_model_rate_limit.apply_async(
        kwargs={
            "model_id": model_id,
            "probe_token": probe_token,
            "probe_attempt": probe_attempt,
        },
        headers={"tenant_id": tenant_id},
        countdown=_PROBE_DELAYS[probe_attempt],
    )


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
    name="bisheng.worker.model_rate_limit.probe_aliyun_model_rate_limit",
)
def probe_aliyun_model_rate_limit(
    self,
    model_id: int,
    probe_token: str,
    probe_attempt: int,
) -> str:
    return _run_in_task_tenant(
        request=self.request,
        coroutine_factory=lambda: run_model_rate_limit_probe(
            tenant_id=_require_tenant_id_header(self.request),
            model_id=model_id,
            probe_token=probe_token,
            probe_attempt=probe_attempt,
        ),
    ).value


def _run_in_task_tenant(*, request: Any, coroutine_factory: Callable[[], Awaitable[ProbeOutcome]]) -> ProbeOutcome:
    tenant_id = _require_tenant_id_header(request)
    token = set_current_tenant_id(tenant_id)
    try:
        return run_async_task(coroutine_factory)
    finally:
        current_tenant_id.reset(token)


def _require_tenant_id_header(request: Any) -> int:
    raw_tenant_id = (getattr(request, "headers", None) or {}).get("tenant_id")
    if raw_tenant_id is None or isinstance(raw_tenant_id, bool):
        raise ValueError("model rate-limit probe requires a tenant_id header")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("model rate-limit probe tenant_id must be a positive integer") from exc
    if tenant_id <= 0:
        raise ValueError("model rate-limit probe tenant_id must be a positive integer")
    return tenant_id


def _outcome(
    result: ProbeOutcome,
    tenant_id: int,
    model_id: int,
    probe_attempt: int,
) -> ProbeOutcome:
    emit_metric(
        "model_rate_limit_probe_total",
        result=result.value,
        tenant_id=tenant_id,
        model_id=model_id,
        probe_attempt=probe_attempt,
    )
    return result

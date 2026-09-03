from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from bisheng.llm.domain.services.aliyun_rate_limit_classifier import (
    AliyunRateLimitClassifier,
    AliyunRateLimitObservation,
)
from bisheng.llm.domain.services.call_logger import ModelRateLimitDiagnostics
from bisheng.llm.domain.services.model_rate_limit_state import (
    ModelRateLimitState,
    ModelRateLimitStateService,
    ModelRateLimitView,
)


class RecoveryAction(StrEnum):
    MANUAL_RETRY = "manual_retry"
    SWITCH_MODEL = "switch_model"


class ModelCallEntry:
    DAILY = "daily"
    TASK = "task"
    KNOWLEDGE = "knowledge"
    CHANNEL = "channel"


class ModelCallResumeMode:
    CHECKPOINT = "checkpoint"
    REINVOKE = "reinvoke"
    READ_ONLY_REINVOKE = "read_only_reinvoke"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class RecoveryCommand:
    execution_id: str
    attempt_id: str
    subject_id: str
    action: RecoveryAction
    target_model_id: int | None = None


@dataclass(frozen=True, slots=True)
class ModelCallContext:
    tenant_id: int
    user_id: int
    model_id: int
    entry: str
    execution_id: str
    attempt_id: str
    subject_type: str
    subject_id: str
    resume_mode: str
    action: RecoveryAction | None = None


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    execution_id: str
    attempt_id: str
    subject_id: str
    entry: str
    model_id: int
    resume_mode: str
    action: RecoveryAction
    should_execute: bool


@dataclass(slots=True)
class RecoverySubject:
    execution_id: str
    subject_type: str
    subject_id: str
    active_model_id: int = 0


class RecoveryPort(Protocol):
    """Business-owned authorization and model eligibility boundary."""

    async def ensure_subject_access(self, execution: RecoverySubject) -> None: ...

    async def ensure_target_model(
        self,
        execution: RecoverySubject,
        model_id: int,
        *,
        allow_busy: bool = False,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ResolvedModelConfig:
    model: Any
    server: Any


@dataclass(frozen=True, slots=True)
class RateLimitObservation:
    execution_id: str
    attempt_id: str
    error_type: str
    rate_limit_state: ModelRateLimitState | None
    busy_until: datetime | None
    status_version: int | None
    subject_id: str
    model_id: int | None = None


class RateLimitStatePort(Protocol):
    async def mark_busy(self, tenant_id: int, model_id: int): ...

    async def clear_if_version(
        self,
        tenant_id: int,
        model_id: int,
        observed_version: int,
    ) -> bool: ...

    async def list_states(
        self,
        tenant_id: int,
        model_ids: list[int],
    ) -> dict[int, ModelRateLimitView]: ...


ModelResolver = Callable[[int], Awaitable[ResolvedModelConfig]]
ProbeScheduler = Callable[..., Awaitable[None]]


async def resolve_model_config(model_id: int) -> ResolvedModelConfig:
    from bisheng.llm.domain.share_fallback import (
        aget_model_by_id_with_share_fallback,
        aget_server_by_id_with_share_fallback,
    )

    model = await aget_model_by_id_with_share_fallback(model_id, cache=True)
    if model is None:
        raise LookupError(f"model {model_id} was not found")
    if model.server_id is None:
        raise LookupError(f"model {model_id} has no server")
    server = await aget_server_by_id_with_share_fallback(model.server_id, cache=True)
    if server is None:
        raise LookupError(f"server {model.server_id} was not found")
    return ResolvedModelConfig(model=model, server=server)


async def schedule_model_rate_limit_probe(
    *,
    tenant_id: int,
    model_id: int,
    probe_token: str,
    probe_attempt: int,
) -> None:
    from bisheng.worker.model_rate_limit import enqueue_model_rate_limit_probe

    await enqueue_model_rate_limit_probe(
        tenant_id=tenant_id,
        model_id=model_id,
        probe_token=probe_token,
        probe_attempt=probe_attempt,
    )


class ModelRateLimitService:
    """Classify user-call failures and maintain only model-level busy state."""

    def __init__(
        self,
        *,
        state_service: RateLimitStatePort | None = None,
        model_resolver: ModelResolver = resolve_model_config,
        schedule_probe: ProbeScheduler = schedule_model_rate_limit_probe,
        diagnostics: Any = ModelRateLimitDiagnostics,
    ) -> None:
        self._state_service = state_service or ModelRateLimitStateService()
        self._model_resolver = model_resolver
        self._schedule_probe = schedule_probe
        self._diagnostics = diagnostics

    async def observe_call_failure(
        self,
        context: ModelCallContext,
        exc: BaseException,
    ) -> RateLimitObservation | None:
        try:
            resolved = await self._model_resolver(context.model_id)
        except Exception as exc:
            self._diagnostics.state_write_failed(
                tenant_id=context.tenant_id,
                model_id=context.model_id,
                entry=context.entry,
                execution_id=context.execution_id,
                attempt_id=context.attempt_id,
                operation="resolve_model",
                error_type=type(exc).__name__,
            )
            return None
        provider_observation = AliyunRateLimitClassifier.classify(
            model=resolved.model,
            server=resolved.server,
            exc=exc,
        )
        if provider_observation is None:
            return None

        state_view = await self._mark_model_busy(context, provider_observation)
        self._emit_detected(context, resolved, provider_observation)

        return RateLimitObservation(
            execution_id=context.execution_id,
            attempt_id=context.attempt_id,
            error_type="rate_limit",
            rate_limit_state=state_view.rate_limit_state if state_view else None,
            busy_until=state_view.busy_until if state_view else None,
            status_version=state_view.status_version if state_view else None,
            subject_id=context.subject_id,
            model_id=context.model_id,
        )

    async def observe_call_success(
        self,
        context: ModelCallContext,
        observed_status_version: int | None,
    ) -> None:
        if observed_status_version is not None:
            try:
                await self._state_service.clear_if_version(
                    context.tenant_id,
                    context.model_id,
                    observed_status_version,
                )
            except Exception as exc:
                self._diagnostics.state_write_failed(
                    tenant_id=context.tenant_id,
                    model_id=context.model_id,
                    entry=context.entry,
                    execution_id=context.execution_id,
                    attempt_id=context.attempt_id,
                    operation="clear_success",
                    error_type=type(exc).__name__,
                )

        return None

    async def list_model_states(
        self,
        tenant_id: int,
        model_ids: list[int],
    ) -> dict[int, ModelRateLimitView]:
        try:
            return await self._state_service.list_states(tenant_id, model_ids)
        except Exception as exc:
            self._diagnostics.state_write_failed(
                tenant_id=tenant_id,
                operation="list_states",
                error_type=type(exc).__name__,
            )
            return {
                model_id: ModelRateLimitView(
                    model_id=model_id,
                    rate_limit_state=ModelRateLimitState.NORMAL,
                    busy_until=None,
                    status_version=0,
                )
                for model_id in model_ids
            }

    async def _mark_model_busy(
        self,
        context: ModelCallContext,
        observation: AliyunRateLimitObservation,
    ) -> ModelRateLimitView | None:
        try:
            marked = await self._state_service.mark_busy(context.tenant_id, observation.model_id)
        except Exception as exc:
            self._diagnostics.state_write_failed(
                tenant_id=context.tenant_id,
                model_id=observation.model_id,
                entry=context.entry,
                execution_id=context.execution_id,
                attempt_id=context.attempt_id,
                operation="mark_busy",
                error_type=type(exc).__name__,
            )
            return None

        if marked.should_schedule:
            try:
                await self._schedule_probe(
                    tenant_id=context.tenant_id,
                    model_id=observation.model_id,
                    probe_token=marked.probe_token,
                    probe_attempt=1,
                )
            except Exception as exc:
                self._diagnostics.state_write_failed(
                    tenant_id=context.tenant_id,
                    model_id=observation.model_id,
                    operation="schedule_probe",
                    error_type=type(exc).__name__,
                )
        return marked.view

    def _emit_detected(
        self,
        context: ModelCallContext,
        resolved: ResolvedModelConfig,
        observation: AliyunRateLimitObservation,
    ) -> None:
        self._diagnostics.rate_limit_detected(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            model_id=observation.model_id,
            server_id=getattr(resolved.server, "id", None),
            entry=context.entry,
            execution_id=context.execution_id,
            attempt_id=context.attempt_id,
            provider_code=observation.provider_code,
            request_id=observation.request_id,
            masked_detail=observation.masked_detail,
        )


class ModelRateLimitCallObserver:
    """Best-effort adapter for one business model-call context."""

    def __init__(
        self,
        context: ModelCallContext,
        service: ModelRateLimitService | None = None,
    ) -> None:
        self._context = context
        self._service = service or ModelRateLimitService()

    async def read_status_version(self) -> int | None:
        states = await self._service.list_model_states(
            self._context.tenant_id,
            [self._context.model_id],
        )
        status_version = states[self._context.model_id].status_version
        return status_version if status_version > 0 else None

    async def observe_failure(self, exc: Exception) -> None:
        await self._service.observe_call_failure(self._context, exc)

    async def observe_success(self, observed_status_version: int | None) -> None:
        await self._service.observe_call_success(self._context, observed_status_version)

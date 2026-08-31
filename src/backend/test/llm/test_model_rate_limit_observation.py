from dataclasses import fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from bisheng.llm.domain.services.model_rate_limit import (
    ModelCallContext,
    ModelCallEntry,
    ModelCallResumeMode,
    ModelRateLimitService,
    RateLimitObservation,
    RecoveryAction,
    ResolvedModelConfig,
)
from bisheng.llm.domain.services.model_rate_limit_state import (
    MarkBusyResult,
    ModelRateLimitState,
    ModelRateLimitView,
)


class ProviderError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str, request_id: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


class FakeStateService:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.fail_write = fail_write
        self.marked: list[tuple[int, int]] = []
        self.cleared: list[tuple[int, int, int]] = []

    async def mark_busy(self, tenant_id: int, model_id: int) -> MarkBusyResult:
        if self.fail_write:
            raise ConnectionError("redis unavailable")
        self.marked.append((tenant_id, model_id))
        return MarkBusyResult(
            view=ModelRateLimitView(
                model_id=model_id,
                rate_limit_state=ModelRateLimitState.RECOVERING,
                busy_until=datetime.now(UTC) + timedelta(seconds=300),
                status_version=4,
            ),
            should_schedule=True,
            probe_token="probe-1",
        )

    async def clear_if_version(self, tenant_id: int, model_id: int, observed_version: int) -> bool:
        self.cleared.append((tenant_id, model_id, observed_version))
        return True

    async def list_states(self, tenant_id: int, model_ids: list[int]):
        return {
            model_id: ModelRateLimitView(
                model_id=model_id,
                rate_limit_state=ModelRateLimitState.NORMAL,
                busy_until=None,
                status_version=0,
            )
            for model_id in model_ids
        }


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.detected: list[dict] = []
        self.write_failures: list[dict] = []

    def rate_limit_detected(self, **values) -> None:
        self.detected.append(values)

    def state_write_failed(self, **values) -> None:
        self.write_failures.append(values)


def context(*, entry: str = ModelCallEntry.DAILY, action: RecoveryAction | None = None):
    return ModelCallContext(
        tenant_id=2,
        user_id=9,
        model_id=17,
        entry=entry,
        execution_id=f"execution-{entry}",
        attempt_id=f"attempt-{entry}",
        subject_type="chat_message",
        subject_id=f"subject-{entry}",
        resume_mode=ModelCallResumeMode.CHECKPOINT,
        action=action,
    )


def rate_limit_error() -> ProviderError:
    return ProviderError(
        "rate limit: api_key=super-secret prompt=do-not-log",
        status_code=429,
        code="Throttling.RateQuota",
        request_id="request-123",
    )


def resolved(*, aliyun: bool = True) -> ResolvedModelConfig:
    server = SimpleNamespace(
        id=6,
        type="qwen" if aliyun else "openai",
        config={"endpoint": "https://dashscope.aliyuncs.com" if aliyun else "https://api.openai.com"},
    )
    return ResolvedModelConfig(model=SimpleNamespace(id=17, server_id=6), server=server)


def service(*, fail_state_write: bool = False, aliyun: bool = True):
    state = FakeStateService(fail_write=fail_state_write)
    diagnostics = RecordingDiagnostics()
    scheduled: list[dict] = []

    async def resolver(model_id: int) -> ResolvedModelConfig:
        assert model_id == 17
        return resolved(aliyun=aliyun)

    async def schedule_probe(**payload) -> None:
        scheduled.append(payload)

    svc = ModelRateLimitService(
        state_service=state,
        model_resolver=resolver,
        schedule_probe=schedule_probe,
        diagnostics=diagnostics,
    )
    return svc, state, diagnostics, scheduled


async def test_real_user_limit_marks_only_model_state_and_schedules_probe() -> None:
    svc, state, _, scheduled = service()
    ctx = context()

    result = await svc.observe_call_failure(ctx, rate_limit_error())

    assert result is not None
    assert result.error_type == "rate_limit"
    assert result.execution_id == ctx.execution_id
    assert result.attempt_id == ctx.attempt_id
    assert result.subject_id == ctx.subject_id
    assert result.rate_limit_state == ModelRateLimitState.RECOVERING
    assert state.marked == [(2, 17)]
    assert scheduled == [{"tenant_id": 2, "model_id": 17, "probe_token": "probe-1", "probe_attempt": 1}]


async def test_recovery_limit_does_not_create_server_side_attempt_state() -> None:
    svc, state, _, _ = service()

    result = await svc.observe_call_failure(
        context(action=RecoveryAction.MANUAL_RETRY),
        rate_limit_error(),
    )

    assert result is not None
    assert state.marked == [(2, 17)]
    assert "manual_rate_limit_count" not in {field.name for field in fields(RateLimitObservation)}


async def test_non_aliyun_429_does_not_write_state_or_schedule_probe() -> None:
    svc, state, diagnostics, scheduled = service(aliyun=False)

    result = await svc.observe_call_failure(context(), rate_limit_error())

    assert result is None
    assert state.marked == []
    assert diagnostics.detected == []
    assert scheduled == []


async def test_success_only_clears_observed_model_version() -> None:
    svc, state, _, _ = service()

    result = await svc.observe_call_success(context(action=RecoveryAction.SWITCH_MODEL), 7)

    assert result is None
    assert state.cleared == [(2, 17, 7)]


async def test_redis_write_failure_keeps_standard_error_without_probe() -> None:
    svc, _, diagnostics, scheduled = service(fail_state_write=True)

    result = await svc.observe_call_failure(context(), rate_limit_error())

    assert result is not None
    assert result.rate_limit_state is None
    assert result.status_version is None
    assert scheduled == []
    assert diagnostics.write_failures[0]["tenant_id"] == 2


async def test_terminal_observation_has_no_provider_raw_diagnostics_fields() -> None:
    svc, _, diagnostics, _ = service()

    result = await svc.observe_call_failure(context(), rate_limit_error())

    assert result is not None
    terminal_fields = {field.name for field in fields(RateLimitObservation)}
    assert not {"provider_code", "request_id", "detail", "masked_detail"} & terminal_fields
    diagnostic = diagnostics.detected[0]
    assert diagnostic["provider_code"] == "Throttling.RateQuota"
    assert diagnostic["request_id"] == "request-123"
    assert "super-secret" not in diagnostic["masked_detail"]
    assert "do-not-log" not in diagnostic["masked_detail"]
    assert "prompt" not in diagnostic


@pytest.mark.parametrize(
    "entry",
    [ModelCallEntry.DAILY, ModelCallEntry.TASK, ModelCallEntry.KNOWLEDGE, ModelCallEntry.CHANNEL],
)
async def test_all_entries_share_the_same_stateless_limit_contract(entry: str) -> None:
    svc, _, _, _ = service()

    result = await svc.observe_call_failure(context(entry=entry), rate_limit_error())

    assert result is not None
    assert result.execution_id == f"execution-{entry}"
    assert result.subject_id == f"subject-{entry}"

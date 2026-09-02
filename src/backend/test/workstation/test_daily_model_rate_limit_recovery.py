import json
from types import SimpleNamespace

import pytest
from fastapi.responses import StreamingResponse

from bisheng.llm.domain.services.model_rate_limit import (
    ClaimedAttempt,
    ModelCallEntry,
    ModelCallResumeMode,
    RateLimitObservation,
    RecoveryAction,
    RecoveryCommand,
)
from bisheng.llm.domain.services.model_rate_limit_state import ModelRateLimitState
from bisheng.llm.domain.services.model_recovery_service import RecoveryNotAllowedError
from bisheng.workstation.api.endpoints.chat import (
    DailyChatRecoveryRequest,
    recover_chat_execution,
)
from bisheng.workstation.domain.services.chat_service import (
    DailyChatRecoveryService,
    build_daily_model_call_context,
    build_daily_rate_limit_sse,
)


class FakeRecoveryService:
    def __init__(self, *, should_execute: bool = True) -> None:
        self.should_execute = should_execute
        self.claims = []
        self.released = []

    async def claim_recovery(
        self,
        command,
        *,
        tenant_id,
        user_id,
        entry,
        subject_type,
        resume_mode,
        port,
    ):
        self.claims.append((command, tenant_id, user_id, port))
        await port.ensure_subject_access(
            SimpleNamespace(
                execution_id=command.execution_id,
                subject_id=command.subject_id,
                active_model_id=17,
            )
        )
        await port.ensure_target_model(SimpleNamespace(active_model_id=17), command.target_model_id or 17)
        return ClaimedAttempt(
            execution_id=command.execution_id,
            attempt_id=command.attempt_id,
            subject_id=command.subject_id,
            entry=entry,
            model_id=command.target_model_id or 17,
            resume_mode=resume_mode,
            action=command.action,
            should_execute=self.should_execute,
        )

    async def release_recovery_lock(self, attempt, *, tenant_id, user_id):
        self.released.append((attempt.attempt_id, tenant_id, user_id))


class FakeDailyPort:
    def __init__(self) -> None:
        self.subject_checks = 0
        self.model_checks = []
        self.resumed = []

    async def ensure_subject_access(self, execution) -> None:
        self.subject_checks += 1

    async def ensure_target_model(self, execution, model_id: int, *, allow_busy: bool = False) -> None:
        self.model_checks.append(model_id)

    async def resume_attempt(self, attempt: ClaimedAttempt):
        self.resumed.append(attempt)
        return {"stream": "same-position", "attempt_id": attempt.attempt_id}


def user():
    return SimpleNamespace(user_id=9, tenant_id=2)


async def test_recover_reauthorizes_claims_and_resumes_only_after_successful_claim() -> None:
    executions = FakeRecoveryService()
    port = FakeDailyPort()
    service = DailyChatRecoveryService(recovery_service=executions, port_factory=lambda _: port)
    command = RecoveryCommand(
        execution_id="execution-1",
        attempt_id="attempt-2",
        subject_id="101",
        action=RecoveryAction.MANUAL_RETRY,
    )

    result = await service.recover(command, login_user=user())

    assert port.subject_checks == 1
    assert port.model_checks == [17]
    assert len(port.resumed) == 1
    assert result.should_execute is True
    assert result.payload == {"stream": "same-position", "attempt_id": "attempt-2"}


async def test_idempotent_replay_does_not_resume_model_twice() -> None:
    executions = FakeRecoveryService(should_execute=False)
    port = FakeDailyPort()
    service = DailyChatRecoveryService(recovery_service=executions, port_factory=lambda _: port)
    command = RecoveryCommand(
        execution_id="execution-1",
        attempt_id="attempt-2",
        subject_id="101",
        action=RecoveryAction.MANUAL_RETRY,
    )

    result = await service.recover(command, login_user=user())

    assert result.should_execute is False
    assert result.payload is None
    assert port.resumed == []


@pytest.mark.parametrize("error", [RuntimeError("setup failed"), RecoveryNotAllowedError("checkpoint unavailable")])
async def test_recovery_setup_failure_is_returned_without_persisting_attempt_state(error: Exception) -> None:
    executions = FakeRecoveryService()
    port = FakeDailyPort()

    async def fail_resume(_attempt):
        raise error

    port.resume_attempt = fail_resume
    service = DailyChatRecoveryService(recovery_service=executions, port_factory=lambda _: port)
    command = RecoveryCommand(
        execution_id="execution-1",
        attempt_id="attempt-2",
        subject_id="101",
        action=RecoveryAction.MANUAL_RETRY,
    )

    with pytest.raises(type(error), match=str(error)):
        await service.recover(command, login_user=user())

    assert port.resumed == []
    assert executions.released == [("attempt-2", 2, 9)]


async def test_recovery_validation_failure_returns_standard_sse(monkeypatch) -> None:
    class RejectingRecoveryService:
        def __init__(self, **_kwargs) -> None:
            pass

        async def recover(self, *_args, **_kwargs):
            raise RecoveryNotAllowedError("recovery rejected")

    monkeypatch.setattr(
        "bisheng.workstation.api.endpoints.chat.DailyChatRecoveryService",
        RejectingRecoveryService,
    )

    response = await recover_chat_execution(
        execution_id="execution-1",
        data=DailyChatRecoveryRequest(
            attempt_id="attempt-2",
            subject_id="101",
            action=RecoveryAction.MANUAL_RETRY,
            target_model_id=17,
        ),
        request=SimpleNamespace(),
        login_user=user(),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert response.media_type == "text/event-stream"
    assert body.startswith("event: error\n")
    payload = json.loads(body.split("data: ", 1)[1])
    assert payload["status_code"] == 12048
    assert payload["data"]["execution_id"] == "execution-1"
    assert payload["data"]["attempt_id"] == "attempt-2"
    assert payload["data"]["error_type"] == "recovery_rejected"


async def test_recovery_endpoint_releases_short_lock_after_stream_finishes(monkeypatch) -> None:
    released = []

    class TrackingRecoveryService:
        async def release_lock_after_stream(self, stream, attempt, *, tenant_id, user_id):
            try:
                async for item in stream:
                    yield item
            finally:
                released.append((attempt.attempt_id, tenant_id, user_id))

    class SuccessfulDailyRecoveryService:
        def __init__(self, *, recovery_service, **_kwargs) -> None:
            self.recovery_service = recovery_service

        async def recover(self, command, *, login_user):
            async def stream():
                yield "event: end\ndata: {}\n\n"

            attempt = ClaimedAttempt(
                execution_id=command.execution_id,
                attempt_id=command.attempt_id,
                subject_id=command.subject_id,
                entry=ModelCallEntry.DAILY,
                model_id=17,
                resume_mode=ModelCallResumeMode.REINVOKE,
                action=command.action,
                should_execute=True,
            )
            return SimpleNamespace(
                payload=StreamingResponse(stream(), media_type="text/event-stream"),
                attempt=attempt,
            )

    monkeypatch.setattr(
        "bisheng.workstation.api.endpoints.chat.ModelRecoveryService",
        TrackingRecoveryService,
    )
    monkeypatch.setattr(
        "bisheng.workstation.api.endpoints.chat.DailyChatRecoveryService",
        SuccessfulDailyRecoveryService,
    )

    response = await recover_chat_execution(
        execution_id="execution-1",
        data=DailyChatRecoveryRequest(
            attempt_id="attempt-2",
            subject_id="101",
            action=RecoveryAction.MANUAL_RETRY,
        ),
        request=SimpleNamespace(),
        login_user=user(),
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == ["event: end\ndata: {}\n\n"]
    assert released == [("attempt-2", 2, 9)]


def test_initial_context_binds_execution_to_persisted_question_without_content() -> None:
    context = build_daily_model_call_context(
        tenant_id=2,
        user_id=9,
        model_id=17,
        execution_id="execution-1",
        attempt_id="attempt-1",
        question_message_id=101,
    )

    assert context.entry == ModelCallEntry.DAILY
    assert context.subject_type == "chat_message"
    assert context.subject_id == "101"
    assert context.resume_mode == ModelCallResumeMode.REINVOKE
    assert not hasattr(context, "prompt")


def test_rate_limit_sse_contains_standard_state_without_provider_detail() -> None:
    observation = RateLimitObservation(
        execution_id="execution-1",
        attempt_id="attempt-1",
        error_type="rate_limit",
        rate_limit_state=ModelRateLimitState.RECOVERING,
        busy_until=None,
        status_version=4,
        subject_id="101",
    )

    event = build_daily_rate_limit_sse(observation)
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["status_code"] == 12046
    assert payload["data"]["execution_id"] == "execution-1"
    assert payload["data"]["attempt_id"] == "attempt-1"
    assert payload["data"]["rate_limit_state"] == "recovering"
    assert payload["data"]["recovery_subject_id"] == "101"
    assert "detail" not in payload["data"]
    assert "request_id" not in payload["data"]


@pytest.mark.parametrize("execution_id", ["execution-old", "execution-new"])
def test_new_requests_keep_distinct_execution_ids(execution_id: str) -> None:
    context = build_daily_model_call_context(
        tenant_id=2,
        user_id=9,
        model_id=17,
        execution_id=execution_id,
        attempt_id=f"attempt-{execution_id}",
        question_message_id=101 if execution_id.endswith("old") else 102,
    )

    assert context.execution_id == execution_id
    assert context.subject_id in {"101", "102"}

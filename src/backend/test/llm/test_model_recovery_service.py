import json
from types import SimpleNamespace

import pytest

from bisheng.llm.domain.services.model_rate_limit import (
    ModelCallEntry,
    ModelCallResumeMode,
    RecoveryAction,
    RecoveryCommand,
)
from bisheng.llm.domain.services.model_recovery_service import (
    ModelRecoveryService,
    build_recovery_rejected_sse,
)


class FakeRedisConnection:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = list(results or [True])
        self.calls: list[tuple] = []
        self.eval_calls: list[tuple] = []
        self.values: dict[str, str] = {}

    async def set(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = self.results.pop(0)
        if result:
            self.values[args[0]] = args[1]
        return result

    async def eval(self, *args):
        self.eval_calls.append(args)
        _, _, key, attempt_id = args
        if self.values.get(key) != attempt_id:
            return 0
        self.values.pop(key, None)
        return 1


class FakePort:
    def __init__(self, *, source_model_id: int = 17) -> None:
        self.source_model_id = source_model_id
        self.subjects = []
        self.targets = []

    async def ensure_subject_access(self, subject) -> None:
        self.subjects.append(subject)
        subject.active_model_id = self.source_model_id

    async def ensure_target_model(self, subject, model_id: int, *, allow_busy: bool = False) -> None:
        self.targets.append((subject, model_id, allow_busy))


def command(action=RecoveryAction.MANUAL_RETRY, target_model_id=None):
    return RecoveryCommand(
        execution_id="execution-1",
        attempt_id="attempt-1",
        subject_id="question-9",
        action=action,
        target_model_id=target_model_id,
    )


async def build_service(results: list[bool] | None = None):
    connection = FakeRedisConnection(results)

    async def redis_factory():
        return SimpleNamespace(async_connection=connection)

    return ModelRecoveryService(redis_factory=redis_factory), connection


async def claim(service, port, recovery_command):
    return await service.claim_recovery(
        recovery_command,
        tenant_id=2,
        user_id=9,
        entry=ModelCallEntry.DAILY,
        subject_type="chat_message",
        resume_mode=ModelCallResumeMode.CHECKPOINT,
        port=port,
    )


async def test_manual_retry_uses_model_from_authorized_business_record() -> None:
    service, connection = await build_service()
    port = FakePort(source_model_id=17)

    attempt = await claim(service, port, command())

    assert attempt.subject_id == "question-9"
    assert attempt.model_id == 17
    assert attempt.should_execute is True
    assert port.targets[0][1] == 17
    assert port.targets[0][2] is True
    _, options = connection.calls[0]
    assert options == {"nx": True, "ex": 5}


async def test_switch_model_uses_confirmed_target_without_persisting_execution_state() -> None:
    service, _ = await build_service()
    port = FakePort(source_model_id=17)

    attempt = await claim(service, port, command(RecoveryAction.SWITCH_MODEL, 23))

    assert attempt.model_id == 23
    assert port.targets[0][1] == 23
    assert port.targets[0][2] is False
    assert not hasattr(attempt, "manual_rate_limit_count")


async def test_short_lock_rejects_only_near_simultaneous_duplicate() -> None:
    service, _ = await build_service([True, False])
    port = FakePort()

    first = await claim(service, port, command())
    second = await claim(service, port, command())

    assert first.should_execute is True
    assert second.should_execute is False


async def test_short_lock_is_released_when_recovery_stream_finishes() -> None:
    service, connection = await build_service()
    attempt = await claim(service, FakePort(), command())

    async def stream():
        yield "event-1"

    wrapped = service.release_lock_after_stream(
        stream(),
        attempt,
        tenant_id=2,
        user_id=9,
    )
    assert await anext(wrapped) == "event-1"
    assert connection.eval_calls == []

    with pytest.raises(StopAsyncIteration):
        await anext(wrapped)

    assert connection.values == {}
    assert connection.eval_calls[-1][2:] == (
        "model-recovery-lock:2:9:daily:question-9",
        "attempt-1",
    )


async def test_completed_attempt_cannot_release_a_newer_recovery_lock() -> None:
    service, connection = await build_service()
    attempt = await claim(service, FakePort(), command())
    key = "model-recovery-lock:2:9:daily:question-9"
    connection.values[key] = "newer-attempt"

    await service.release_recovery_lock(attempt, tenant_id=2, user_id=9)

    assert connection.values[key] == "newer-attempt"


async def test_manual_retry_uses_current_page_model_when_provided() -> None:
    service, _ = await build_service()
    port = FakePort(source_model_id=17)

    attempt = await claim(service, port, command(target_model_id=23))

    assert attempt.model_id == 23
    assert port.targets[0][1] == 23
    assert port.targets[0][2] is True


async def test_switch_can_confirm_the_current_page_model() -> None:
    service, _ = await build_service()
    port = FakePort(source_model_id=17)

    attempt = await claim(service, port, command(RecoveryAction.SWITCH_MODEL, 17))

    assert attempt.model_id == 17
    assert port.targets[0][1] == 17
    assert port.targets[0][2] is False


async def test_redis_outage_fails_open_without_creating_durable_state() -> None:
    async def failing_redis_factory():
        raise ConnectionError("redis unavailable")

    service = ModelRecoveryService(redis_factory=failing_redis_factory)

    attempt = await claim(service, FakePort(), command())

    assert attempt.should_execute is True


def test_duplicate_recovery_uses_standard_sse_error_envelope() -> None:
    attempt = SimpleNamespace(
        execution_id="execution-1",
        attempt_id="attempt-2",
        subject_id="question-9",
        model_id=17,
    )

    event = build_recovery_rejected_sse(attempt)
    payload = json.loads(event.split("data: ", 1)[1])

    assert event.startswith("event: error\n")
    assert payload["status_code"] == 12048
    assert payload["data"]["execution_id"] == "execution-1"
    assert payload["data"]["attempt_id"] == "attempt-2"
    assert payload["data"]["error_type"] == "recovery_rejected"
    assert payload["data"]["recovery_subject_id"] == "question-9"
    assert payload["data"]["model_id"] == 17


def test_validation_rejection_uses_standard_sse_error_envelope() -> None:
    event = build_recovery_rejected_sse(command(target_model_id=23))
    payload = json.loads(event.split("data: ", 1)[1])

    assert event.startswith("event: error\n")
    assert payload["status_code"] == 12048
    assert payload["data"]["execution_id"] == "execution-1"
    assert payload["data"]["attempt_id"] == "attempt-1"
    assert payload["data"]["error_type"] == "recovery_rejected"
    assert payload["data"]["recovery_subject_id"] == "question-9"
    assert payload["data"]["model_id"] == 23

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain.services.resilience_middleware import (
    LinsightModelResilienceMiddleware,
)
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.llm.domain.services.model_rate_limit_state import ModelRateLimitState


class FakeRequest:
    messages = []
    tools = []
    runtime = SimpleNamespace(config={"configurable": {"thread_id": "session-1"}})

    def override(self, **values):
        copy = FakeRequest()
        for key, value in values.items():
            setattr(copy, key, value)
        return copy


async def test_confirmed_aliyun_rate_limit_uses_existing_resilience_retry(monkeypatch) -> None:
    calls = 0
    observed = []

    async def observe_failure(exc):
        observed.append(exc)

    async def handler(request):
        nonlocal calls
        calls += 1
        raise RuntimeError("429")

    middleware = LinsightModelResilienceMiddleware(
        max_retries=3,
        initial_delay=0,
        failure_observer=observe_failure,
    )

    monkeypatch.setattr(
        "bisheng.linsight.domain.services.resilience_middleware.classify_behavior",
        lambda exc: (
            __import__(
                "bisheng.common.services.llm_error_classifier",
                fromlist=["Behavior"],
            ).Behavior.RETRYABLE
        ),
    )

    with pytest.raises(RuntimeError, match="429"):
        await middleware.awrap_model_call(FakeRequest(), handler)

    assert calls == 4
    assert len(observed) == 4


async def test_non_aliyun_retryable_error_keeps_existing_retry_policy(monkeypatch) -> None:
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("timed out")
        return SimpleNamespace(result=[])

    monkeypatch.setattr(
        "bisheng.linsight.domain.services.resilience_middleware.classify_behavior",
        lambda exc: (
            __import__(
                "bisheng.common.services.llm_error_classifier",
                fromlist=["Behavior"],
            ).Behavior.RETRYABLE
        ),
    )
    middleware = LinsightModelResilienceMiddleware(
        max_retries=3,
        initial_delay=0,
    )

    await middleware.awrap_model_call(FakeRequest(), handler)

    assert calls == 3


async def test_rate_limit_failure_uses_existing_task_failure_lifecycle(monkeypatch) -> None:
    writes = []
    persisted_turns = []
    terminated = []
    task = LinsightWorkflowTask()
    task.session_version_id = "session-1"
    task._state_manager = SimpleNamespace(
        set_session_version_info=lambda session: _record(writes, "session", session),
        push_message=lambda message: _record(writes, "event", message),
    )

    async def persist_task_turn(session):
        persisted_turns.append(session)

    async def terminate_unfinished_tasks():
        terminated.append(True)

    async def get_all_config():
        return {}

    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.LinsightSessionVersionDao.get_by_id",
        AsyncMock(return_value=SimpleNamespace(id="session-1", tenant_id=2, user_id=7, model="18")),
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.linsight_execute_utils.persist_task_turn_message",
        persist_task_turn,
    )
    monkeypatch.setattr(
        "bisheng.common.services.config_service.ConfigService.aget_all_config",
        get_all_config,
    )
    task._terminate_unfinished_tasks = terminate_unfinished_tasks

    class FakeRateLimitService:
        async def list_model_states(self, tenant_id, model_ids):
            assert tenant_id == 2
            assert model_ids == [18]
            return {18: SimpleNamespace(rate_limit_state=ModelRateLimitState.BUSY)}

    monkeypatch.setattr("bisheng.linsight.domain.task_exec.ModelRateLimitService", FakeRateLimitService)

    await task._handle_execution_error(RuntimeError("429 rate limit"))

    session = writes[0][1]
    assert session.output_result["error_type"] == "rate_limit"
    assert session.output_result["rate_limit_state"] == "busy"
    assert session.output_result["model_id"] == 18
    assert persisted_turns == [session]
    assert terminated == [True]
    assert [kind for kind, _ in writes] == ["session", "event"]
    assert writes[-1][1].data["error_type"] == "rate_limit"
    assert writes[-1][1].data["rate_limit_state"] == "busy"
    assert writes[-1][1].data["model_id"] == 18


async def test_rate_limit_retry_uses_only_existing_continue_workflow(monkeypatch) -> None:
    continued = []
    session = SimpleNamespace(id="session-1", tenant_id=2, user_id=7, model="18")

    class UnexpectedRateLimitService:
        def __init__(self):
            raise AssertionError("task continuation must not infer model-call success")

    async def restore_tenant_context(_session_version_id):
        return None

    @asynccontextmanager
    async def managed_resume():
        yield session

    async def continue_workflow(session_model, question):
        continued.append((session_model, question))

    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.ModelRateLimitService",
        UnexpectedRateLimitService,
    )
    task = LinsightWorkflowTask()
    task._restore_tenant_context = restore_tenant_context
    task._managed_resume = managed_resume
    task._continue_workflow = continue_workflow

    await task.async_continue("session-1", "retry the original question")

    assert continued == [(session, "retry the original question")]


async def test_non_rate_limit_failure_does_not_inherit_existing_busy_projection(monkeypatch) -> None:
    session = SimpleNamespace(id="session-1", tenant_id=2, user_id=7, model="18")
    handled = AsyncMock()

    class UnexpectedRateLimitService:
        def __init__(self):
            raise AssertionError("non-rate-limit failures must not read the busy projection")

    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.LinsightSessionVersionDao.get_by_id",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.ModelRateLimitService",
        UnexpectedRateLimitService,
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.task_exec.classify_for_event",
        lambda _error: SimpleNamespace(error_type="network_timeout"),
    )
    task = LinsightWorkflowTask()
    task.session_version_id = "session-1"
    task._handle_task_failure = handled

    await task._handle_execution_error(TimeoutError("timed out"))

    handled.assert_awaited_once()
    args, kwargs = handled.await_args
    assert args == (session, "timed out")
    assert isinstance(kwargs["exc"], TimeoutError)
    assert kwargs["extra_payload"] is None


async def _record(records, kind, value):
    records.append((kind, value))

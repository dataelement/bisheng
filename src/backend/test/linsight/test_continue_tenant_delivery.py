"""A retry must reach the worker with its tenant and selected model intact."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.linsight import LinsightStartTaskError
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id
from bisheng.linsight import worker
from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
from bisheng.linsight.domain.services import workbench_impl


@pytest.fixture
def failed_round(monkeypatch):
    session = SimpleNamespace(
        id="version-1",
        session_id="chat-1",
        tenant_id=7,
        user_id=9,
        status=SessionVersionStatusEnum.FAILED,
        model="82",
        output_result=None,
    )
    items = []

    class RedisQueue:
        async def arpush(self, key, value, expiration):
            items.append(value)

    async def update_status(ids, status, **kwargs):
        assert ids == [session.id]
        session.status = status
        if "model" in kwargs:
            session.model = kwargs["model"]

    updates = AsyncMock(side_effect=update_status)
    monkeypatch.setattr(workbench_impl, "get_redis_client", AsyncMock(return_value=RedisQueue()))
    monkeypatch.setattr(workbench_impl.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session))
    monkeypatch.setattr(workbench_impl.LinsightSessionVersionDao, "batch_update_session_versions_status", updates)
    monkeypatch.setattr(workbench_impl.MessageSessionDao, "touch_session", AsyncMock())
    monkeypatch.setattr(workbench_impl.LinsightWorkbenchImpl, "_validate_continue_model", AsyncMock())
    return session, items, updates


@pytest.mark.parametrize("model_id", [None, "22"])
async def test_retry_round_trips_real_queue_payload_into_tenant_scoped_worker(failed_round, monkeypatch, model_id):
    session, items, _ = failed_round
    token = current_tenant_id.set(None)
    try:
        await workbench_impl.LinsightWorkbenchImpl.continue_conversation(
            session.id,
            "Original question",
            SimpleNamespace(user_id=session.user_id),
            model_id=model_id,
        )
        assert len(items) == 1
        payload = worker.parse_queue_item(items[0])
        assert payload["tenant_id"] == session.tenant_id
        assert payload["continue_question"] == "Original question"
        assert session.status == SessionVersionStatusEnum.IN_PROGRESS
        assert session.model == (model_id or "82")

        executed = []

        @asynccontextmanager
        async def managed_resume():
            assert get_current_tenant_id() == session.tenant_id
            yield session

        async def continue_workflow(current_session, question):
            executed.append((current_session.id, question, current_session.model, get_current_tenant_id()))

        monkeypatch.setattr(task_exec, "ensure_linsight_permission_runtime", AsyncMock())
        task = task_exec.LinsightWorkflowTask()
        task._managed_resume = managed_resume
        task._continue_workflow = continue_workflow
        task._handle_execution_error = AsyncMock()
        await task.async_continue(
            payload["session_version_id"], payload["continue_question"], tenant_id=payload["tenant_id"]
        )
        assert executed == [(session.id, "Original question", model_id or "82", session.tenant_id)]
        task._handle_execution_error.assert_not_awaited()
        assert get_current_tenant_id() is None
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("tenant_id", [None, 0, -1, True, "bad"])
async def test_retry_rejects_invalid_persisted_tenant_before_entering_running_state(failed_round, tenant_id):
    session, items, updates = failed_round
    session.tenant_id = tenant_id
    with pytest.raises(LinsightStartTaskError):
        await workbench_impl.LinsightWorkbenchImpl.continue_conversation(
            session.id,
            "Original question",
            SimpleNamespace(user_id=session.user_id),
            model_id="22",
        )
    assert session.status == SessionVersionStatusEnum.FAILED
    assert session.model == "82"
    assert items == []
    updates.assert_not_awaited()


async def test_failure_to_persist_terminal_state_reaches_existing_worker_safety_net(monkeypatch):
    """The done callback cannot repair a failure that task_exec hides as success."""
    task = task_exec.LinsightWorkflowTask()
    task.session_version_id = "version-1"
    monkeypatch.setattr(
        task_exec.LinsightSessionVersionDao,
        "get_by_id",
        AsyncMock(side_effect=RuntimeError("Missing tenant context")),
    )
    proc = worker.ScheduleCenterProcess.__new__(worker.ScheduleCenterProcess)
    proc.semaphore = None
    proc.repair_tasks = set()
    proc._force_fail_stranded_session = AsyncMock()
    result = asyncio.create_task(task._handle_execution_error(RuntimeError("failed to start continuation")))
    await asyncio.wait({result})
    proc.handle_task_result(result, session_version_id=task.session_version_id)
    repairs = list(proc.repair_tasks)
    if repairs:
        await asyncio.gather(*repairs)
    proc._force_fail_stranded_session.assert_awaited_once()
    assert proc._force_fail_stranded_session.await_args.args[0] == task.session_version_id


async def test_successfully_persisted_failure_does_not_trigger_worker_safety_net(monkeypatch):
    task = task_exec.LinsightWorkflowTask()
    task.session_version_id = "version-1"
    session = SimpleNamespace(tenant_id=7, model="82")
    monkeypatch.setattr(task_exec.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session))
    task._handle_task_failure = AsyncMock()
    await task._handle_execution_error(RuntimeError("ordinary task failure"))
    task._handle_task_failure.assert_awaited_once()

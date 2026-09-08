"""One session_version_id must not be finalized by two worker processes.

Continue/resume used to skip the IN_PROGRESS guard (the comment claimed a
parked session stayed IN_PROGRESS; park actually writes WAITING_FOR_USER_INPUT).
Two queue items for the same svid then both wrote FINAL_RESULT onto the same
ChatMessage row, and the later wrap-up erased a cited report.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import bisheng.core.cache.redis_manager as redis_manager_mod
from bisheng.linsight.domain import task_exec as te
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.task_exec import (
    LINSIGHT_RUN_LOCK_KEY_PREFIX,
    LINSIGHT_RUN_LOCK_TTL_SECONDS,
    LinsightWorkflowTask,
    TaskAlreadyInProgressError,
)
from test.linsight.test_deferred_ingest_worker import FakeStateManager


def _session(*, status=SessionVersionStatusEnum.COMPLETED, svid: str = "svid-lock"):
    return LinsightSessionVersion(
        id=svid,
        session_id="chat1",
        user_id=7,
        question="q",
        status=status,
        tenant_id=3,
    )


def _task(session_model) -> tuple[LinsightWorkflowTask, FakeStateManager]:
    task = LinsightWorkflowTask()
    task.session_version_id = session_model.id
    state = FakeStateManager(session_model)
    task._state_manager = state
    return task, state


@pytest.fixture
def fail_open_lock(monkeypatch: pytest.MonkeyPatch):
    """Existing resume/execution tests must not need a live Redis."""

    @asynccontextmanager
    async def _open(_self):
        yield

    monkeypatch.setattr(LinsightWorkflowTask, "_acquire_session_run_lock", _open)


@pytest.fixture
def redis_lock(monkeypatch: pytest.MonkeyPatch):
    client = SimpleNamespace(
        async_connection=SimpleNamespace(set=AsyncMock(return_value=True)),
        adelete=AsyncMock(),
    )
    monkeypatch.setattr(redis_manager_mod, "get_redis_client", AsyncMock(return_value=client))
    return client


async def test_run_lock_uses_set_nx_ex_and_releases(redis_lock):
    task = LinsightWorkflowTask()
    task.session_version_id = "sv-lock"
    async with task._acquire_session_run_lock():
        pass
    redis_lock.async_connection.set.assert_awaited_once_with(
        f"{LINSIGHT_RUN_LOCK_KEY_PREFIX}sv-lock",
        b"1",
        nx=True,
        ex=LINSIGHT_RUN_LOCK_TTL_SECONDS,
    )
    redis_lock.adelete.assert_awaited_once_with(f"{LINSIGHT_RUN_LOCK_KEY_PREFIX}sv-lock")


async def test_run_lock_rejects_when_already_held(redis_lock):
    redis_lock.async_connection.set.return_value = False
    task = LinsightWorkflowTask()
    task.session_version_id = "sv-lock"
    with pytest.raises(TaskAlreadyInProgressError):
        async with task._acquire_session_run_lock():
            raise AssertionError("second driver must not enter")
    redis_lock.adelete.assert_not_awaited()


async def test_run_lock_fail_open_when_redis_client_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        redis_manager_mod,
        "get_redis_client",
        AsyncMock(side_effect=RuntimeError("redis manager missing")),
    )
    task = LinsightWorkflowTask()
    task.session_version_id = "sv-lock"
    entered = False
    async with task._acquire_session_run_lock():
        entered = True
    assert entered is True


async def test_managed_resume_rejects_in_progress(monkeypatch: pytest.MonkeyPatch, fail_open_lock):
    session_model = _session(status=SessionVersionStatusEnum.IN_PROGRESS)
    task, state = _task(session_model)
    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    task._start_termination_monitor = AsyncMock()
    task._ensure_session_pseudo_task = AsyncMock()
    task._init_file_directory = AsyncMock(return_value="/tmp/linsight-sv")

    with pytest.raises(TaskAlreadyInProgressError):
        async with task._managed_resume():
            raise AssertionError("must not drive an in-progress session")
    task._init_file_directory.assert_not_awaited()


async def test_managed_resume_allows_waiting_for_user_input(monkeypatch: pytest.MonkeyPatch, fail_open_lock):
    session_model = _session(status=SessionVersionStatusEnum.WAITING_FOR_USER_INPUT)
    task, state = _task(session_model)
    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    task._start_termination_monitor = AsyncMock()
    task._ensure_session_pseudo_task = AsyncMock()
    task._ingest_pending_attachments = AsyncMock()
    task._init_file_directory = AsyncMock(return_value="/tmp/linsight-sv")

    async with task._managed_resume() as resumed:
        assert resumed.id == session_model.id
    task._init_file_directory.assert_awaited_once()


async def test_async_continue_swallows_in_progress_and_does_not_fail_session(
    monkeypatch: pytest.MonkeyPatch,
):
    task = LinsightWorkflowTask()
    task._restore_tenant_context = AsyncMock(return_value=None)
    task._handle_execution_error = AsyncMock()
    task._managed_resume = MagicMock(side_effect=TaskAlreadyInProgressError("Task already in progress"))
    monkeypatch.setattr(te, "ensure_linsight_permission_runtime", AsyncMock(return_value={}))

    await task.async_continue("sv-lock", "追问", tenant_id=3)

    task._handle_execution_error.assert_not_awaited()

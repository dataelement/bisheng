"""One session_version_id must not be finalized by two worker processes.

Continue/resume used to have no mutual exclusion at all: two queue items for
the same svid both wrote FINAL_RESULT onto the same ChatMessage row, and the
later wrap-up erased a cited report. The Redis driver lock is the ONLY mutex for
continue/resume — the DB status cannot be one, because /workbench/continue
flips the row to IN_PROGRESS before it enqueues, so every follow-up turn
arrives in that status. The lock itself (taken in ``_unified_run_scope``) is
covered by ``test_planned_run_unified.py``; this file covers the status handling.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.linsight.domain import task_exec as te
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, TaskAlreadyInProgressError
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


async def test_managed_resume_enters_in_progress_after_api_flip(monkeypatch: pytest.MonkeyPatch, fail_open_lock):
    """/workbench/continue writes IN_PROGRESS before enqueue, so a follow-up
    turn always arrives in that status and must still be driven; a DB status
    guard here rejected every follow-up and left the session stuck as running."""
    session_model = _session(status=SessionVersionStatusEnum.IN_PROGRESS)
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

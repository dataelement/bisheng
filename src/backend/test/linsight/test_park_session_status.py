"""Regression for park-and-release SESSION-version status (root cause #2).

When an ``ask_user`` interrupt parks a task, the *session-version* status must
flip to ``WAITING_FOR_USER_INPUT`` — NOT stay ``IN_PROGRESS``. Otherwise the
worker-startup crash sweep (``check_and_terminate_incomplete_tasks`` scans
``IN_PROGRESS``; a parked task's Redis owner key is released by park-and-release)
wrongly marks the parked task ``FAILED`` ("Worker node crash detected"). A
dedicated ``WAITING_FOR_USER_INPUT`` session status keeps parked tasks out of
that ``IN_PROGRESS`` sweep (see ``test_check_and_terminate_tenant`` which asserts
the sweep queries ``IN_PROGRESS``); resume flips it back to ``IN_PROGRESS``.

These tests pin the two status flips deterministically — the e2e path depends on
the model actually choosing to call ``ask_user``, which is a separate (model
adherence) concern and is unreliable to trigger on demand.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum


def test_session_version_enum_has_waiting_for_user_input():
    """A dedicated session-level WAITING status must exist (root cause #2 fix).

    Without it, park has no non-IN_PROGRESS state to set and the crash sweep
    误杀s parked tasks.
    """
    assert hasattr(SessionVersionStatusEnum, "WAITING_FOR_USER_INPUT")
    assert SessionVersionStatusEnum.WAITING_FOR_USER_INPUT.value == "waiting_for_user_input"


async def test_handle_need_user_input_parks_session_as_waiting():
    """park (ask_user interrupt) flips session_version.status to WAITING_FOR_USER_INPUT.

    Guards root cause #2: a parked session left at IN_PROGRESS is swept to FAILED
    by the worker-startup crash check.
    """
    from bisheng.linsight.domain import task_exec as te

    exec_task = te.LinsightWorkflowTask()
    sm = MagicMock()
    sm.add_execution_task_step = AsyncMock()
    sm.update_execution_task_status = AsyncMock()
    sm.push_message = AsyncMock()
    sm.set_session_version_info = AsyncMock()  # _update_session_status persists via this
    exec_task._state_manager = sm

    session = MagicMock()
    session.id = "svid-park-1"
    session.status = SessionVersionStatusEnum.IN_PROGRESS

    event = MagicMock()
    event.task_id = "svid-park-1"
    event.model_dump.return_value = {"task_id": "svid-park-1", "step_type": "call_user_input"}

    await exec_task._handle_need_user_input(None, event, session)

    # parked flag set so _handle_task_completion skips the direct-answer fallback
    assert exec_task._waiting_for_input is True
    # SESSION-version status flipped to WAITING — keeps it out of the IN_PROGRESS sweep
    assert session.status == SessionVersionStatusEnum.WAITING_FOR_USER_INPUT
    sm.set_session_version_info.assert_awaited()  # the new status was persisted


async def test_resume_workflow_resets_session_in_progress():
    """Resuming a parked (WAITING) task flips session_version.status back to IN_PROGRESS.

    The flip is the first statement in ``_resume_workflow`` (before any LLM/agent
    work), so making ``_get_llm`` raise short-circuits the heavy body right after
    the status flip we want to assert.
    """
    from bisheng.linsight.domain import task_exec as te

    exec_task = te.LinsightWorkflowTask()
    sm = MagicMock()
    sm.set_session_version_info = AsyncMock()
    exec_task._state_manager = sm

    session = MagicMock()
    session.id = "svid-resume-1"
    session.status = SessionVersionStatusEnum.WAITING_FOR_USER_INPUT

    # Short-circuit the heavy resume body right after the status flip.
    exec_task._get_llm = AsyncMock(side_effect=RuntimeError("stop after status flip"))

    with pytest.raises(RuntimeError):
        await exec_task._resume_workflow(session, user_input="我身高175体重80")

    assert session.status == SessionVersionStatusEnum.IN_PROGRESS
    sm.set_session_version_info.assert_awaited()

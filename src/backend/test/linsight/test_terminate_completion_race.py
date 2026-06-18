"""Terminate-vs-complete race (2026-06-18 bugfix).

A stop request can land while the agent is finishing its final step. The
background termination monitor polls on an interval, so a task that completes
inside the poll window escapes the cancel and the agent returns "success" —
``_handle_task_completion`` would then overwrite the user's TERMINATED status
with COMPLETED and the stop is silently lost (the task delivers a full result
despite the user clicking stop — observed live on 2026-06-18 when stopping at
the last ``write_file`` step).

The fix re-reads the authoritative status at the top of
``_handle_task_completion`` and honours a termination that arrived before
completion instead of clobbering it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng_langchain.linsight.const import TaskStatus


def _task() -> LinsightWorkflowTask:
    task = LinsightWorkflowTask()
    task.session_version_id = "SV-1"
    task._waiting_for_input = False
    return task


async def test_completion_honours_termination_over_success():
    """A terminate that landed just before completion wins — no COMPLETED overwrite.

    Simulates the race: the agent finished normally (``_final_result`` is a
    SUCCESS TaskEnd), but a stop request set the session TERMINATED in Redis
    before completion ran, so ``_check_user_termination`` returns True.
    """
    task = _task()
    task._check_user_termination = AsyncMock(return_value=True)
    task._handle_user_termination = AsyncMock()
    task._handle_task_success = AsyncMock()
    task._handle_direct_answer_completion = AsyncMock()
    task._final_result = SimpleNamespace(status=TaskStatus.SUCCESS.value, answer="full report")

    session = SimpleNamespace(id="SV-1")
    await task._handle_task_completion(session)

    # Termination is honoured; the success/direct-answer paths never run, so the
    # TERMINATED status is not overwritten with COMPLETED.
    task._handle_user_termination.assert_awaited_once_with(session)
    task._handle_task_success.assert_not_awaited()
    task._handle_direct_answer_completion.assert_not_awaited()


async def test_completion_proceeds_when_not_terminated():
    """No terminate → normal success completion is unaffected by the guard."""
    task = _task()
    task._check_user_termination = AsyncMock(return_value=False)
    task._handle_user_termination = AsyncMock()
    task._handle_task_success = AsyncMock()
    task._final_result = SimpleNamespace(status=TaskStatus.SUCCESS.value, answer="done")

    session = SimpleNamespace(id="SV-1")
    await task._handle_task_completion(session)

    task._handle_task_success.assert_awaited_once_with(session)
    task._handle_user_termination.assert_not_awaited()

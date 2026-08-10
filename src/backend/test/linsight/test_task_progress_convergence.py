"""The task table must converge, so the panel never reports a fake ratio.

Background — session ``aa352cb4…`` (180 POC, v2.6.0-fix2, 2026-08-08): a run that
finished successfully showed "任务已完成 4/7". ``linsight_execute_task`` was
effectively append-only — rows were inserted from the FIRST ``write_todos``
snapshot, then only ever touched on a status flip:

- todos the model pruned from its plan produced no event at all (the mapper's own
  comment claimed they were "marked TERMINATED", but the code only dropped them
  from the in-memory projection), so their rows sat at ``not_started`` forever;
- none of the three normal completion paths swept leftovers, so the session ended
  COMPLETED with 1 IN_PROGRESS + 2 NOT_STARTED still in the table;
- a rewritten todo kept the title from the very first draft.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    ExecuteTaskTypeEnum,
    LinsightExecuteTask,
)
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng_langchain.linsight.event import GenerateSubTask, TaskEnd, TaskStart

SVID = "1f3c9a20-7b4e-4d11-9c3a-0a1b2c3d4e5f"


def _task_id(content: str) -> str:
    return hashlib.md5(f"{SVID}:{content}".encode()).hexdigest()[:8]


@pytest.fixture
def mapper() -> StreamEventMapper:
    return StreamEventMapper(svid=SVID)


def _todos(*pairs) -> list[dict]:
    return [{"content": c, "status": s} for c, s in pairs]


def _feed(mapper: StreamEventMapper, todos: list[dict]):
    return mapper._diff_todos(todos)


def _of(events, kind):
    return [e for e in events if isinstance(e, kind)]


# --------------------------------------------------------------------------
# Mapper: pruned todos produce a terminal event
# --------------------------------------------------------------------------


def test_vanished_todo_emits_a_terminated_task_end(mapper):
    _feed(mapper, _todos(("调研", "completed"), ("撰写", "in_progress"), ("配图", "pending")))
    events = _feed(mapper, _todos(("调研", "completed"), ("撰写", "completed")))

    dropped = [e for e in _of(events, TaskEnd) if e.status == "terminated"]
    assert len(dropped) == 1
    assert dropped[0].task_id == _task_id("配图")
    # Non-empty data so _handle_task_end also repairs the row's title.
    assert dropped[0].data["name"] == "配图"


def test_vanished_completed_todo_is_left_alone(mapper):
    """Pruning the plan after delivery does not un-deliver the work."""
    _feed(mapper, _todos(("调研", "completed"), ("撰写", "completed")))
    events = _feed(mapper, _todos(("调研", "completed")))

    assert [e for e in _of(events, TaskEnd) if e.status == "terminated"] == []


def test_vanished_todo_leaves_the_projection(mapper):
    _feed(mapper, _todos(("a", "pending"), ("b", "pending"), ("c", "pending")))
    _feed(mapper, _todos(("a", "pending")))
    assert [p.content for p in mapper.ctx.todos] == ["a"]


def test_reordering_terminates_nothing(mapper):
    """Level-1 exact-content matching must survive a shuffle."""
    _feed(mapper, _todos(("a", "pending"), ("b", "pending")))
    events = _feed(mapper, _todos(("b", "pending"), ("a", "pending")))
    assert [e for e in _of(events, TaskEnd) if e.status == "terminated"] == []


def test_first_snapshot_terminates_nothing(mapper):
    events = _feed(mapper, _todos(("a", "pending"), ("b", "pending")))
    assert _of(events, TaskEnd) == []
    assert len(_of(events, GenerateSubTask)) == 1


def test_rewritten_todo_is_republished_for_task_data_sync(mapper):
    """Positional alignment keeps the row id, so the new wording has to be pushed
    or the panel keeps showing the first draft's title after a refresh."""
    _feed(
        mapper,
        _todos(
            ("写初稿", "in_progress"),
        ),
    )
    events = _feed(
        mapper,
        _todos(
            ("写初稿并配图", "in_progress"),
        ),
    )

    generated = _of(events, GenerateSubTask)
    assert len(generated) == 1
    entry = generated[0].subtask[0]
    assert entry["id"] == _task_id("写初稿")  # id reused
    assert entry["name"] == "写初稿并配图"  # title refreshed
    # Same status → no spurious start/end.
    assert _of(events, TaskStart) == []


# --------------------------------------------------------------------------
# task_exec: a dropped todo must never become the run's outcome
# --------------------------------------------------------------------------


def _exec_task() -> LinsightWorkflowTask:
    task = LinsightWorkflowTask()
    task.session_version_id = "svid"
    sm = MagicMock()
    sm.update_execution_task_status = AsyncMock(return_value={"id": "t1"})
    sm.push_message = AsyncMock()
    task._state_manager = sm
    return task


def _end(task_id: str, status: str, data: dict | None = None) -> TaskEnd:
    return TaskEnd(task_id=task_id, name="n", status=status, answer="", data=data or {})


async def test_terminated_task_end_writes_terminated_status():
    task = _exec_task()
    await task._handle_task_end(None, _end("t1", "terminated", {"name": "配图"}), None)

    kwargs = task._state_manager.update_execution_task_status.await_args.kwargs
    assert kwargs["status"] is ExecuteTaskStatusEnum.TERMINATED
    assert kwargs["task_data"] == {"name": "配图"}


async def test_terminated_task_end_never_becomes_the_final_result():
    """Gate-keeper: ``_handle_task_completion`` routes any non-success
    ``_final_result`` into ``_handle_task_failure``. A todo the model pruned
    arriving last would therefore fail the WHOLE session."""
    task = _exec_task()
    success = _end("t1", "success")
    await task._handle_task_end(None, success, None)
    await task._handle_task_end(None, _end("t2", "terminated"), None)

    assert task._final_result is success


async def test_success_task_end_still_sets_the_final_result():
    task = _exec_task()
    success = _end("t1", "success")
    await task._handle_task_end(None, success, None)
    assert task._final_result is success
    kwargs = task._state_manager.update_execution_task_status.await_args.kwargs
    assert kwargs["status"] is ExecuteTaskStatusEnum.SUCCESS


async def test_failed_task_end_still_maps_to_failed():
    task = _exec_task()
    await task._handle_task_end(None, _end("t1", "failed"), None)
    kwargs = task._state_manager.update_execution_task_status.await_args.kwargs
    assert kwargs["status"] is ExecuteTaskStatusEnum.FAILED


# --------------------------------------------------------------------------
# task_exec: completion sweeps whatever the run left hanging
# --------------------------------------------------------------------------


def _row(tid: str, status: ExecuteTaskStatusEnum, *, pseudo: bool = False) -> LinsightExecuteTask:
    return LinsightExecuteTask(
        id=tid,
        session_version_id="svid",
        parent_task_id=None,
        task_type=ExecuteTaskTypeEnum.SINGLE,
        status=status,
        task_data={"name": tid, **({"is_session_global": True} if pseudo else {})},
        history=[],
    )


def _sweepable_task() -> LinsightWorkflowTask:
    task = LinsightWorkflowTask()
    task.session_version_id = "svid"
    sm = MagicMock()
    sm.get_execution_tasks = AsyncMock(
        return_value=[
            _row("done", ExecuteTaskStatusEnum.SUCCESS),
            _row("running", ExecuteTaskStatusEnum.IN_PROGRESS),
            _row("never", ExecuteTaskStatusEnum.NOT_STARTED),
        ]
    )
    sm.update_execution_task_status = AsyncMock(return_value={})
    task._state_manager = sm
    return task


def _swept(task) -> dict[str, ExecuteTaskStatusEnum]:
    return {
        call.kwargs["task_id"]: call.kwargs["status"]
        for call in task._state_manager.update_execution_task_status.await_args_list
    }


async def test_completion_sweep_converges_unfinished_rows():
    task = _sweepable_task()
    await task._converge_task_rows_on_completion()

    swept = _swept(task)
    assert swept == {"running": ExecuteTaskStatusEnum.TERMINATED, "never": ExecuteTaskStatusEnum.TERMINATED}
    assert "done" not in swept  # a delivered row is never downgraded


async def test_sweep_is_idempotent():
    task = LinsightWorkflowTask()
    task.session_version_id = "svid"
    sm = MagicMock()
    sm.get_execution_tasks = AsyncMock(
        return_value=[
            _row("a", ExecuteTaskStatusEnum.SUCCESS),
            _row("b", ExecuteTaskStatusEnum.TERMINATED),
            _row("c", ExecuteTaskStatusEnum.FAILED),
        ]
    )
    sm.update_execution_task_status = AsyncMock(return_value={})
    task._state_manager = sm

    await task._converge_task_rows_on_completion()
    assert sm.update_execution_task_status.await_count == 0


async def test_sweep_runs_after_the_pseudo_task_is_finalized():
    """ORDERING gate-keeper: the sweep walks every row including the svid pseudo
    task, so finalizing that one first is what keeps the session's own row from
    being marked TERMINATED on a successful run."""
    task = LinsightWorkflowTask()
    task.session_version_id = "svid"
    order: list[str] = []

    sm = MagicMock()

    async def _update(task_id, status, **kwargs):
        order.append(f"{task_id}:{status.value}")
        return {}

    sm.update_execution_task_status = AsyncMock(side_effect=_update)
    sm.get_execution_tasks = AsyncMock(
        return_value=[
            _row("svid", ExecuteTaskStatusEnum.SUCCESS, pseudo=True),
            _row("t1", ExecuteTaskStatusEnum.NOT_STARTED),
        ]
    )
    task._state_manager = sm

    session_model = MagicMock()
    session_model.id = "svid"
    await task._complete_session_pseudo_task(session_model)
    await task._converge_task_rows_on_completion()

    assert order == ["svid:success", "t1:terminated"]

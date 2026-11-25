"""F004 T030: persistence projector of a ``planned`` run (design 决策 6, 8; K4).

Consumes the unified events of one run and keeps ``linsight_execute_task`` equal
to the latest ``plan`` event: one row per plan item, the row id is the item id.

Differences from ``task_exec._save_task_info`` (same table, same ``task_data``
keys, same batch insert of new rows):

* existing rows are written with ``update_fields_by_id`` (one UPDATE, changed
  columns only). Nothing here loads a whole row: ``history`` grows with the run
  and reading it back is what exhausted worker memory on DM8.
* ``task_data`` gains ``previous_name`` (wording before the latest rewrite,
  AC-10) and ``plan_index`` (position in the current plan), so a reload returns
  the plan in the order and wording of the last ``plan`` event (AC-11).
* an item the model dropped is stored as ``TERMINATED`` and stays in the plan.
* writes are throttled: at most one flush per ``min_interval`` seconds, plus one
  at the end. A ``plan`` event always carries the whole plan, so skipping
  intermediate ones loses nothing.

The cache of what the table holds is rebuilt from the table on the first flush,
so a projector started in another process (resume after a question, relay)
continues from the rows instead of inserting them again.

Interface: ``async on_event(event)`` and ``async aclose()``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    ExecuteTaskTypeEnum,
    LinsightExecuteTask,
    LinsightExecuteTaskDao,
)
from bisheng.linsight.domain.schemas import run_events

DEFAULT_MIN_INTERVAL_SECONDS = 1.0

PLAN_INDEX_KEY = "plan_index"
PREVIOUS_NAME_KEY = "previous_name"

_DB_STATUS_BY_PLAN_STATUS = {
    run_events.PLAN_PENDING: ExecuteTaskStatusEnum.NOT_STARTED,
    run_events.PLAN_IN_PROGRESS: ExecuteTaskStatusEnum.IN_PROGRESS,
    run_events.PLAN_COMPLETED: ExecuteTaskStatusEnum.SUCCESS,
    run_events.PLAN_CANCELLED: ExecuteTaskStatusEnum.TERMINATED,
}
_PLAN_STATUS_BY_DB_STATUS = {
    ExecuteTaskStatusEnum.NOT_STARTED: run_events.PLAN_PENDING,
    ExecuteTaskStatusEnum.IN_PROGRESS: run_events.PLAN_IN_PROGRESS,
    ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT: run_events.PLAN_IN_PROGRESS,
    ExecuteTaskStatusEnum.USER_INPUT_COMPLETED: run_events.PLAN_IN_PROGRESS,
    ExecuteTaskStatusEnum.SUCCESS: run_events.PLAN_COMPLETED,
    ExecuteTaskStatusEnum.TERMINATED: run_events.PLAN_CANCELLED,
    # The plan has no "failed" row state; a failed step is no longer being worked on.
    ExecuteTaskStatusEnum.FAILED: run_events.PLAN_CANCELLED,
}
# Todo status strings, the vocabulary ``task_data["status"]`` already uses.
_TODO_STATUS_BY_PLAN_STATUS = {
    run_events.PLAN_PENDING: "pending",
    run_events.PLAN_IN_PROGRESS: "in_progress",
    run_events.PLAN_COMPLETED: "completed",
    run_events.PLAN_CANCELLED: ExecuteTaskStatusEnum.TERMINATED.value,
}
_ENDED_STATUSES = frozenset({ExecuteTaskStatusEnum.SUCCESS, ExecuteTaskStatusEnum.TERMINATED})


def _as_status(value: Any) -> ExecuteTaskStatusEnum | None:
    if isinstance(value, ExecuteTaskStatusEnum):
        return value
    try:
        return ExecuteTaskStatusEnum(str(value))
    except ValueError:
        try:
            return ExecuteTaskStatusEnum[str(value)]
        except KeyError:
            return None


@dataclass
class _RowState:
    """What the table holds for one row, as far as the plan is concerned."""

    name: str
    previous_name: str | None
    status: ExecuteTaskStatusEnum | None
    # None: the row is not part of the current plan.
    index: int | None

    @classmethod
    def from_columns(cls, status: Any, task_data: Any) -> _RowState:
        data = task_data if isinstance(task_data, dict) else {}
        index = data.get(PLAN_INDEX_KEY)
        return cls(
            name=str(data.get("name") or ""),
            previous_name=data.get(PREVIOUS_NAME_KEY) or None,
            status=_as_status(status),
            index=index if isinstance(index, int) else None,
        )


def _task_data(task_id: str, name: str, previous_name: str | None, plan_status: str | None, index: int | None) -> dict:
    data: dict[str, Any] = {"id": task_id, "task_id": task_id, "name": name}
    if plan_status is not None:
        data["status"] = _TODO_STATUS_BY_PLAN_STATUS.get(plan_status, plan_status)
    if previous_name:
        data[PREVIOUS_NAME_KEY] = previous_name
    if index is not None:
        data[PLAN_INDEX_KEY] = index
    return data


async def load_plan(session_version_id: str, *, dao: Any = LinsightExecuteTaskDao) -> list[dict[str, Any]]:
    """The plan as stored, in the shape of a ``plan`` event's ``items`` (AC-11).

    Rows written by this projector carry their position. A session version from
    before the unified runtime has none; its rows are returned in the order the
    database gives them, all of them.
    """
    rows = await dao.get_plan_columns_by_session_version_id(session_version_id)
    states = [(str(task_id), _RowState.from_columns(status, task_data)) for task_id, status, task_data in rows]
    if any(state.index is not None for _, state in states):
        states = sorted((entry for entry in states if entry[1].index is not None), key=lambda entry: entry[1].index)
    return [
        run_events.PlanItem(
            id=task_id,
            content=state.name,
            previous_content=state.previous_name,
            status=_PLAN_STATUS_BY_DB_STATUS.get(state.status, run_events.PLAN_PENDING),
        ).model_dump(exclude_none=True)
        for task_id, state in states
    ]


class PlannedRunProjector:
    """Keep ``linsight_execute_task`` equal to the latest ``plan`` event of one run."""

    def __init__(
        self,
        session_version_id: str,
        *,
        run_id: str | None = None,
        dao: Any = LinsightExecuteTaskDao,
        min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.session_version_id = session_version_id
        self.run_id = run_id
        self.flush_count = 0
        self._dao = dao
        self._min_interval = min_interval
        self._clock = clock
        self._pending: list[dict[str, Any]] | None = None
        self._rows: dict[str, _RowState] | None = None
        self._last_flush: float | None = None
        self._timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # -- interface -----------------------------------------------------------

    async def on_event(self, event: dict) -> None:
        event_type = event.get("type")
        if event_type == run_events.PLAN:
            items = (event.get("data") or {}).get("items")
            self._pending = [item for item in (items or []) if isinstance(item, dict) and item.get("id")]
            await self._flush_or_defer()
        elif event_type in run_events.TERMINAL_EVENT_TYPES:
            self._cancel_timer()
            await self.flush()

    async def aclose(self) -> None:
        self._cancel_timer()
        await self.flush()

    async def flush(self) -> None:
        """Write the latest plan now, if one is waiting."""
        async with self._lock:
            items, self._pending = self._pending, None
            if items is None:
                return
            try:
                await self._write(items)
            except Exception:
                # Keep the plan for the next flush unless a newer one arrived.
                if self._pending is None:
                    self._pending = items
                # The cache may no longer match the table; reload it next time.
                self._rows = None
                raise
            self._last_flush = self._clock()
            self.flush_count += 1

    # -- throttle --------------------------------------------------------------

    async def _flush_or_defer(self) -> None:
        if self._last_flush is None:
            await self.flush()
            return
        wait = self._min_interval - (self._clock() - self._last_flush)
        if wait <= 0:
            self._cancel_timer()
            await self.flush()
        elif self._timer is None or self._timer.done():
            # Trailing flush: the last plan of a burst is written even when no
            # further event arrives.
            self._timer = asyncio.create_task(self._flush_later(wait))

    async def _flush_later(self, wait: float) -> None:
        await asyncio.sleep(wait)
        self._timer = None
        try:
            await self.flush()
        except Exception:
            # Nobody awaits the timer. The plan stays pending and the next event
            # or ``aclose`` writes it (and raises to the run driver if it fails again).
            logger.exception(
                "planned run projector failed its delayed plan write svid={} run_id={}",
                self.session_version_id,
                self.run_id,
            )

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and not timer.done() and timer is not asyncio.current_task():
            timer.cancel()

    # -- write -------------------------------------------------------------------

    async def _load_rows(self) -> dict[str, _RowState]:
        rows = await self._dao.get_plan_columns_by_session_version_id(self.session_version_id)
        return {str(task_id): _RowState.from_columns(status, task_data) for task_id, status, task_data in rows}

    async def _write(self, items: list[dict[str, Any]]) -> None:
        if self._rows is None:
            self._rows = await self._load_rows()
        known = self._rows

        new_tasks: list[LinsightExecuteTask] = []
        updates: list[tuple[str, dict[str, Any]]] = []
        target: dict[str, _RowState] = {}
        ids = [str(item["id"]) for item in items]

        for index, item in enumerate(items):
            task_id = ids[index]
            if task_id in target:
                logger.warning(
                    "planned run projector: plan repeats an item id svid={} task_id={}",
                    self.session_version_id,
                    task_id,
                )
                continue
            plan_status = item.get("status") or run_events.PLAN_PENDING
            wanted = _RowState(
                name=str(item.get("content") or ""),
                previous_name=item.get("previous_content") or None,
                status=_DB_STATUS_BY_PLAN_STATUS.get(plan_status, ExecuteTaskStatusEnum.NOT_STARTED),
                index=index,
            )
            target[task_id] = wanted
            task_data = _task_data(task_id, wanted.name, wanted.previous_name, plan_status, index)
            current = known.get(task_id)
            if current is None:
                new_tasks.append(
                    LinsightExecuteTask(
                        id=task_id,
                        session_version_id=self.session_version_id,
                        previous_task_id=ids[index - 1] if index > 0 else None,
                        next_task_id=ids[index + 1] if index < len(ids) - 1 else None,
                        task_type=ExecuteTaskTypeEnum.SINGLE,
                        task_data=task_data,
                        status=wanted.status,
                        result={"answer": ""} if wanted.status in _ENDED_STATUSES else None,
                    )
                )
                continue
            fields: dict[str, Any] = {}
            if (current.name, current.previous_name, current.index) != (wanted.name, wanted.previous_name, index):
                fields["task_data"] = task_data
            if current.status != wanted.status:
                fields["status"] = wanted.status
                # ``status`` inside task_data follows the row, as it does at insert.
                fields["task_data"] = task_data
                if wanted.status in _ENDED_STATUSES:
                    # Same value ``task_exec._handle_task_end`` stores for a todo.
                    fields["result"] = {"answer": ""}
            if fields:
                updates.append((task_id, fields))

        # A row that left the plan without being cancelled (a finished step the
        # model no longer lists) keeps its status and loses its position.
        for task_id, current in known.items():
            if task_id in target or current.index is None:
                continue
            target[task_id] = _RowState(current.name, current.previous_name, current.status, None)
            updates.append(
                (task_id, {"task_data": _task_data(task_id, current.name, current.previous_name, None, None)})
            )

        if new_tasks:
            await self._dao.batch_create_tasks(new_tasks)
        for task_id, fields in updates:
            await self._dao.update_fields_by_id(task_id, **fields)

        self._rows = {**known, **target}
        if new_tasks or updates:
            logger.debug(
                "planned run projector wrote plan svid={} run_id={} inserted={} updated={}",
                self.session_version_id,
                self.run_id,
                len(new_tasks),
                len(updates),
            )

"""Share one in-flight read for the same key. Drop the result when it finishes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

_tasks: dict[str, asyncio.Task] = {}
_guard = asyncio.Lock()


def stable_key(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, default=_json_default, separators=(",", ":"))


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def _drop(key: str, task: asyncio.Task) -> None:
    if _tasks.get(key) is task:
        _tasks.pop(key, None)


async def shared_call(key: str, factory: Callable[[], Awaitable[T]]) -> T:
    """A cancelled waiter does not cancel the shared load or the other waiters."""
    async with _guard:
        task = _tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(factory())
            _tasks[key] = task
            task.add_done_callback(lambda finished, flight_key=key: _drop(flight_key, finished))
    return await asyncio.shield(task)

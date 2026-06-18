import asyncio
import time

import pytest

from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.utils.async_utils import run_async_safe


async def _sleep_then_return(delay: float, value: str = "ok") -> str:
    await asyncio.sleep(delay)
    return value


class _LoopBoundSingleton:
    """Mimics a process-wide async client cached on the loop it first ran on.

    OpenFGA's ``httpx.AsyncClient`` (and the aiomysql / aioredis singletons)
    behave like this: pooled connections stay bound to the loop that opened
    them. Driving such a singleton from a fresh ``asyncio.run`` loop on the
    next call hits ``RuntimeError: Event loop is closed``.
    """

    def __init__(self) -> None:
        self._origin_loop = None

    async def use(self) -> int:
        running = asyncio.get_running_loop()
        if self._origin_loop is None:
            self._origin_loop = running
        # Touch the origin loop the way a cached connection's transport does.
        fut = self._origin_loop.create_future()
        self._origin_loop.call_soon(fut.set_result, id(self._origin_loop))
        return await fut


def test_run_async_safe_runs_from_plain_sync_context():
    assert run_async_safe(_sleep_then_return(0), timeout=1) == "ok"


def test_run_async_safe_reuses_one_loop_across_sync_calls():
    """Sequential sync calls must share a single, never-closed loop so cached
    async clients survive between calls (regression: OpenFGA agent-node crash)."""
    singleton = _LoopBoundSingleton()

    first = run_async_safe(singleton.use(), timeout=2)
    second = run_async_safe(singleton.use(), timeout=2)

    assert first == second


def test_run_async_safe_honors_timeout_from_plain_sync_context():
    with pytest.raises(asyncio.TimeoutError):
        run_async_safe(_sleep_then_return(0.2), timeout=0.01)


@pytest.mark.asyncio
async def test_run_async_safe_rejects_running_event_loop_without_waiting():
    start = time.perf_counter()

    with pytest.raises(RuntimeError, match="running event loop"):
        run_async_safe(_sleep_then_return(1), timeout=5)

    assert time.perf_counter() - start < 0.5


@pytest.mark.asyncio
async def test_owner_run_async_safe_reuses_event_loop_guard():
    start = time.perf_counter()

    with pytest.raises(RuntimeError, match="running event loop"):
        _run_async_safe(_sleep_then_return(1), timeout=5)

    assert time.perf_counter() - start < 0.5

import asyncio
import contextvars
import threading
import time

import pytest

from bisheng.permission.domain.services.owner_service import _run_async_safe
from bisheng.utils.async_utils import run_async_safe, run_on_bridge_loop, set_preferred_bridge_loop


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


def _start_persistent_loop() -> asyncio.AbstractEventLoop:
    """Mimic a Celery worker's persistent loop thread (e.g. run_async_task's)."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def _bind_singleton_on(loop: asyncio.AbstractEventLoop, singleton: "_LoopBoundSingleton") -> int:
    """Drive ``singleton.use()`` on ``loop`` so its cached origin loop == ``loop``."""
    return asyncio.run_coroutine_threadsafe(singleton.use(), loop).result(timeout=2)


def test_run_async_safe_cross_loop_singleton_fails_without_shared_loop():
    """Control: a singleton bound on a worker-style loop cannot be driven by
    run_async_safe's own background loop — this is the exact production failure
    ('Future attached to a different loop'). Proves the fix test below is not
    vacuous."""
    set_preferred_bridge_loop(None)
    worker_loop = _start_persistent_loop()
    try:
        singleton = _LoopBoundSingleton()
        _bind_singleton_on(worker_loop, singleton)  # origin loop = worker_loop
        with pytest.raises(RuntimeError, match="different loop"):
            run_async_safe(singleton.use(), timeout=2)  # background loop != worker_loop
    finally:
        worker_loop.call_soon_threadsafe(worker_loop.stop)


def test_run_async_safe_reuses_registered_preferred_loop():
    """Fix: once a worker registers its loop, run_async_safe submits onto that
    same loop, so a singleton bound there is driven cross-thread without any
    cross-loop error."""
    worker_loop = _start_persistent_loop()
    set_preferred_bridge_loop(worker_loop)
    try:
        singleton = _LoopBoundSingleton()
        origin = _bind_singleton_on(worker_loop, singleton)  # origin loop = worker_loop
        result = run_async_safe(singleton.use(), timeout=2)  # must reuse worker_loop
        assert result == origin == id(worker_loop)
    finally:
        set_preferred_bridge_loop(None)
        worker_loop.call_soon_threadsafe(worker_loop.stop)


# ── run_on_bridge_loop: hop async work off a transient/foreign loop ──────────
# Mirrors LangChain running an async callback on a throwaway asyncio.Runner loop
# inside a sync invoke, then touching the shared async DB pool.

_probe_var = contextvars.ContextVar("probe", default="unset")


async def _running_loop_id() -> int:
    return id(asyncio.get_running_loop())


def test_run_on_bridge_loop_hops_to_preferred_from_foreign_loop():
    """A coro driven from a foreign (transient) loop must execute on the
    registered bridge loop, not the foreign one."""
    pref = _start_persistent_loop()
    transient = _start_persistent_loop()
    set_preferred_bridge_loop(pref)
    try:

        async def _driver():
            return await run_on_bridge_loop(_running_loop_id())

        got = asyncio.run_coroutine_threadsafe(_driver(), transient).result(timeout=3)
        assert got == id(pref)
    finally:
        set_preferred_bridge_loop(None)
        pref.call_soon_threadsafe(pref.stop)
        transient.call_soon_threadsafe(transient.stop)


def test_run_on_bridge_loop_propagates_contextvars():
    """Tenant-scoped ContextVars set on the caller must survive the hop — without
    this, ModelCallLogger would raise TenantContextMissingError on the bridge loop."""
    pref = _start_persistent_loop()
    transient = _start_persistent_loop()
    set_preferred_bridge_loop(pref)
    try:

        async def _read():
            return _probe_var.get()

        async def _driver():
            _probe_var.set("tenant-42")
            return await run_on_bridge_loop(_read())

        got = asyncio.run_coroutine_threadsafe(_driver(), transient).result(timeout=3)
        assert got == "tenant-42"
    finally:
        set_preferred_bridge_loop(None)
        pref.call_soon_threadsafe(pref.stop)
        transient.call_soon_threadsafe(transient.stop)


def test_run_on_bridge_loop_runs_inline_without_preferred():
    """No bridge loop registered (FastAPI / scripts): run inline on the current loop."""
    set_preferred_bridge_loop(None)
    current = _start_persistent_loop()
    try:

        async def _driver():
            return await run_on_bridge_loop(_running_loop_id())

        got = asyncio.run_coroutine_threadsafe(_driver(), current).result(timeout=3)
        assert got == id(current)
    finally:
        current.call_soon_threadsafe(current.stop)


def test_run_on_bridge_loop_fixes_cross_loop_singleton():
    """The real fix: a singleton bound on the bridge loop (like a Loop-A pooled DB
    connection) is driven from a transient callback loop WITHOUT a cross-loop error,
    because the work hops onto the bridge loop."""
    pref = _start_persistent_loop()
    transient = _start_persistent_loop()
    set_preferred_bridge_loop(pref)
    try:
        singleton = _LoopBoundSingleton()
        origin = _bind_singleton_on(pref, singleton)  # bound to the bridge loop

        async def _driver():
            return await run_on_bridge_loop(singleton.use())

        got = asyncio.run_coroutine_threadsafe(_driver(), transient).result(timeout=3)
        assert got == origin == id(pref)
    finally:
        set_preferred_bridge_loop(None)
        pref.call_soon_threadsafe(pref.stop)
        transient.call_soon_threadsafe(transient.stop)

"""Async/sync interop helpers shared across the codebase.

Centralizes ``run_async_safe`` for sync callers that need one async result.
The helper is intentionally sync-only: if a caller is already running on an
event-loop thread, it must ``await`` the async API instead of blocking that
same loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading
from collections.abc import Awaitable
from typing import Any


def _close_coroutine(coro: Awaitable[Any]) -> None:
    close = getattr(coro, "close", None)
    if callable(close):
        close()


class _BackgroundLoop:
    """A single, long-lived event loop hosted on a dedicated daemon thread.

    ``asyncio.run`` builds and tears down a fresh loop per call. Process-wide
    async singletons (OpenFGA's ``httpx.AsyncClient``, aiomysql / aioredis
    clients) cache connections bound to the loop that first opened them, so the
    next ``asyncio.run`` call drives those cached connections from a *closed*
    loop and raises ``RuntimeError: Event loop is closed``. Running every sync
    bridge call on ONE persistent loop keeps those connections valid for the
    lifetime of the process. Created lazily so it is fork-safe (each worker
    process spins up its own loop on first use).
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        # Prefer a loop the worker registered so run_async_task and
        # run_async_safe share ONE loop process-wide (see set_preferred_bridge_loop).
        preferred = _preferred_loop
        if preferred is not None and not preferred.is_closed():
            return preferred
        loop = self._loop
        if loop is not None and not loop.is_closed():
            return loop
        with self._lock:
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever,
                name="run-async-safe-loop",
                daemon=True,
            ).start()
            self._loop = loop
            return loop

    def run(self, coro: Awaitable[Any], timeout: float | None) -> Any:
        loop = self._ensure_loop()

        async def _runner():
            if timeout is None:
                return await coro
            return await asyncio.wait_for(coro, timeout=timeout)

        future = asyncio.run_coroutine_threadsafe(_runner(), loop)
        return future.result()


_background_loop = _BackgroundLoop()

# A process may host TWO sync->async bridge loops: the Celery worker's persistent
# loop (``worker/_asyncio_utils`` -> ``run_async_task``) and this module's
# ``_BackgroundLoop`` (``run_async_safe``). Async singletons — OpenFGA's
# ``httpx.AsyncClient``, aiomysql / aioredis — cache connections bound to
# whichever loop first drove them; driving the same singleton from the *other*
# loop raises ``RuntimeError: ... got Future ... attached to a different loop``.
# When the worker registers its loop here, ``run_async_safe`` submits onto it too
# so the whole process shares ONE bridge loop and cached clients never cross loops.
_preferred_loop: asyncio.AbstractEventLoop | None = None


def set_preferred_bridge_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Register a process-wide loop for ``run_async_safe`` to submit onto.

    The Celery worker calls this with its persistent loop so ``run_async_task``
    and ``run_async_safe`` share a single loop. Pass ``None`` to unregister
    (e.g. on worker shutdown). No-op for FastAPI / scripts that never call it.
    """
    global _preferred_loop
    _preferred_loop = loop


def run_async_safe(coro: Awaitable[Any], *, timeout: float = 10) -> Any:
    """Run an async coroutine from a sync context.

    - FastAPI / Starlette sync endpoints run in an AnyIO worker thread; hop
      back to the request loop with ``anyio.from_thread.run`` so async DB /
      Redis / HTTP clients stay on the owning event loop.
    - Plain sync callers without an AnyIO bridge (e.g. Celery worker threads)
      run the coroutine on a single, process-wide persistent loop so cached
      async clients survive across calls (see ``_BackgroundLoop``).
    - Async callers must not use this helper. Blocking a running loop while
      scheduling work back to it deadlocks until the timeout expires.

    Returns the coroutine's result; propagates its exceptions.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        _close_coroutine(coro)
        raise RuntimeError(
            "run_async_safe cannot be called from a running event loop; "
            "await the async API or run the sync caller in an AnyIO/FastAPI threadpool."
        )

    try:
        import anyio

        async def _await(awaitable):
            if timeout is None:
                return await awaitable
            with anyio.fail_after(timeout):
                return await awaitable

        return anyio.from_thread.run(_await, coro)
    except RuntimeError as exc:
        if "AnyIO worker thread" not in str(exc):
            _close_coroutine(coro)
            raise
    except Exception:
        _close_coroutine(coro)
        raise

    return _background_loop.run(coro, timeout)


async def run_on_bridge_loop(coro: Awaitable[Any]) -> Any:
    """Await ``coro`` on the registered bridge loop when the caller runs on a
    foreign/throwaway loop; otherwise await it inline.

    Async callbacks driven by a *sync* run execute on a transient loop that is
    closed immediately after — LangChain runs async callback handlers via a
    per-batch ``asyncio.Runner`` when the surrounding invoke is synchronous. Any
    process-global async client (such as pooled connections of the async DB
    engine) that the callback touches is then left bound to that now-dead loop, poisoning
    the shared pool for later callers ("Future attached to a different loop" /
    "Event loop is closed"). Hopping the work onto the persistent worker bridge
    loop (see ``set_preferred_bridge_loop``) keeps every shared-pool call on ONE
    loop.

    Contextvars (e.g. ``current_tenant_id``) are propagated to the bridge loop so
    tenant-scoped writes keep working. No-op (awaits inline) when no bridge loop
    is registered (FastAPI / scripts) or the caller already runs on it.
    """
    current = asyncio.get_running_loop()
    pref = _preferred_loop
    if pref is None or pref is current or pref.is_closed():
        return await coro

    ctx = contextvars.copy_context()
    result_future: concurrent.futures.Future = concurrent.futures.Future()

    def _schedule() -> None:
        def _on_done(task: asyncio.Task) -> None:
            if task.cancelled():
                result_future.cancel()
            elif (exc := task.exception()) is not None:
                result_future.set_exception(exc)
            else:
                result_future.set_result(task.result())

        def _create() -> None:
            # Creating the task inside ctx.run() propagates all ContextVars
            # (Task.__init__ copies the current context) onto the bridge loop.
            async def _run() -> Any:
                return await coro

            pref.create_task(_run()).add_done_callback(_on_done)

        ctx.run(_create)

    pref.call_soon_threadsafe(_schedule)
    return await asyncio.wrap_future(result_future)

"""Async/sync interop helpers shared across the codebase.

Centralizes ``run_async_safe`` for sync callers that need one async result.
The helper is intentionally sync-only: if a caller is already running on an
event-loop thread, it must ``await`` the async API instead of blocking that
same loop.
"""

from __future__ import annotations

import asyncio
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

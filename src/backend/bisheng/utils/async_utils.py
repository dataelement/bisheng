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

_preferred_bridge_loop: asyncio.AbstractEventLoop | None = None


def _close_coroutine(coro: Awaitable[Any]) -> None:
    close = getattr(coro, "close", None)
    if callable(close):
        close()


class _BackgroundLoop:
    """Host one persistent fallback event loop for plain sync processes."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        thread = self._thread
        if loop is not None and thread is not None and thread.is_alive() and not loop.is_closed():
            return loop

        with self._lock:
            loop = self._loop
            thread = self._thread
            if loop is not None and thread is not None and thread.is_alive() and not loop.is_closed():
                return loop

            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run,
                args=(loop,),
                name="run-async-safe-loop",
                daemon=True,
            )
            thread.start()
            self._loop = loop
            self._thread = thread
            return loop

    @staticmethod
    def _run(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()


_background_loop = _BackgroundLoop()


def set_preferred_bridge_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Register the process loop used by sync-to-async bridge calls."""
    global _preferred_bridge_loop
    _preferred_bridge_loop = loop


def run_async_safe(coro: Awaitable[Any], *, timeout: float | None = 10) -> Any:
    """Run an async coroutine from a sync context.

    - FastAPI / Starlette sync endpoints run in an AnyIO worker thread; hop
      back to the request loop with ``anyio.from_thread.run`` so async DB /
      Redis / HTTP clients stay on the owning event loop.
    - Celery worker threads submit to the registered persistent worker loop.
    - Plain sync callers without an AnyIO or worker bridge reuse one persistent
      fallback loop so process-wide async clients never bind to a closed loop.
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

    async def _run_with_timeout():
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    target_loop = _preferred_bridge_loop
    if target_loop is None or target_loop.is_closed():
        target_loop = _background_loop.get_loop()

    runner = _run_with_timeout()
    try:
        future = asyncio.run_coroutine_threadsafe(runner, target_loop)
    except Exception:
        _close_coroutine(runner)
        _close_coroutine(coro)
        raise
    return future.result()

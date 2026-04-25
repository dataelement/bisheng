"""Async/sync interop helpers shared across the codebase.

Centralizes ``run_async_safe`` for sync callers that need one async result.
The helper is intentionally sync-only: if a caller is already running on an
event-loop thread, it must ``await`` the async API instead of blocking that
same loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable


def _close_coroutine(coro: Awaitable[Any]) -> None:
    close = getattr(coro, 'close', None)
    if callable(close):
        close()


def run_async_safe(coro: Awaitable[Any], *, timeout: float = 10) -> Any:
    """Run an async coroutine from a sync context.

    - FastAPI / Starlette sync endpoints run in an AnyIO worker thread; hop
      back to the request loop with ``anyio.from_thread.run`` so async DB /
      Redis / HTTP clients stay on the owning event loop.
    - Plain sync callers without an AnyIO bridge use a short-lived loop.
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
            'run_async_safe cannot be called from a running event loop; '
            'await the async API or run the sync caller in an AnyIO/FastAPI threadpool.'
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
        if 'AnyIO worker thread' not in str(exc):
            _close_coroutine(coro)
            raise
    except Exception:
        _close_coroutine(coro)
        raise

    async def _run_with_timeout():
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    return asyncio.run(_run_with_timeout())

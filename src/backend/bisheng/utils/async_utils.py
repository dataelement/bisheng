"""Async/sync interop helpers shared across the codebase.

Centralizes ``run_async_safe`` — a small wrapper that dispatches an
awaitable to the right event loop whether the caller is running inside
one (FastAPI threadpool) or not (Celery worker, CLI, alembic upgrade).

Before this module, four services each inlined a byte-identical copy of
the helper (``OwnerService._run_async_safe`` and F017's
``ResourceShareService`` / ``LLMTokenTracker`` / ``ModelCallLogger``);
bug fixes had to land in four places. Everything new should import from
here; the legacy copies forward to this implementation for now.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable


def run_async_safe(coro: Awaitable[Any], *, timeout: float = 10) -> Any:
    """Run an async coroutine from a sync context.

    - If there's already a running event loop (FastAPI threadpool worker
      thread, nested Celery task), dispatch via ``run_coroutine_threadsafe``
      so the coroutine runs on the main loop rather than a new one that
      can't share aiomysql/redis connections.
    - Otherwise (plain sync caller, no loop), spin up a short-lived loop
      with ``asyncio.run``.

    Returns the coroutine's result; propagates its exceptions.
    """
    try:
        loop = asyncio.get_running_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    except RuntimeError:
        return asyncio.run(coro)

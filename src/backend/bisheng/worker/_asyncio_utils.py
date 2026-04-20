"""Shared asyncio glue for Celery tasks.

Celery workers run on a threaded pool with no persistent asyncio
loop, so every task that awaits coroutines creates its own loop,
drives it to completion, and closes it. Replicating that try/finally
across each task adds noise and invites subtle leaks (e.g. forgetting
``loop.close()``). This module centralises the pattern.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar('T')


def run_async_task(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Execute ``coro_factory()`` in a fresh asyncio loop.

    The factory indirection (rather than accepting the coroutine
    directly) avoids the "coroutine was never awaited" warning when
    the caller builds the coroutine eagerly but we error before
    entering the loop.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()

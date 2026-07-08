"""Shared asyncio glue for Celery tasks.

One persistent event-loop thread is started per worker process.  Celery task
threads submit coroutines to it via ``run_async_task`` and block until the
result is ready.

Thread-death safety
-------------------
If the loop thread dies for any reason, ``run_async_task`` will detect it
and call ``os._exit(1)`` so the process supervisor (systemd / Celery prefork)
restarts the worker instead of letting tasks hang forever.

Detection happens at two points:
  1. *Before submission* — catches death between tasks.
  2. *During polling* — ``fut.result(timeout=_POLL_INTERVAL)`` wakes up every
     second while waiting; if the thread is gone it calls ``os._exit(1)``.

Why ``os._exit``?  It bypasses ``atexit`` and Python's SystemExit handling,
guaranteeing an immediate hard exit even from a worker thread.

ContextVar propagation
----------------------
``contextvars.copy_context()`` snapshots the calling Celery thread's vars
(including ``current_tenant_id``).  The snapshot is passed to
``loop.create_task(context=ctx)`` so the coroutine runs with the correct
tenant context on the shared loop thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_lock = threading.Lock()

_POLL_INTERVAL = 1.0  # seconds between liveness checks while blocking


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent per-process async event loop, creating it once."""
    global _loop, _loop_thread
    with _lock:
        if _loop_thread is None or not _loop_thread.is_alive():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(
                target=_loop.run_forever,
                name="bisheng-celery-async",
                daemon=True,
            )
            _loop_thread.start()
            # Route run_async_safe (utils.async_utils) onto THIS loop too, so the
            # worker has a single sync->async bridge loop. Two separate loops let an
            # async singleton (e.g. the OpenFGA httpx client) bind to one loop and
            # then break when driven from the other ("Future attached to a different
            # loop") — see set_preferred_bridge_loop.
            from bisheng.utils.async_utils import set_preferred_bridge_loop

            set_preferred_bridge_loop(_loop)
            logger.debug("Celery async event-loop thread started (tid=%d)", _loop_thread.ident)
    return _loop


def _die_if_loop_dead() -> None:
    if _loop_thread is not None and not _loop_thread.is_alive():
        logger.critical(
            "Celery async event-loop thread has died — calling os._exit(1) "
            "so the process supervisor can restart this worker."
        )
        os._exit(1)


def run_async_task(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Submit ``coro_factory()`` to the persistent worker loop and block until done.

    The factory indirection avoids a "coroutine was never awaited" warning if
    we abort before the loop picks it up.
    """
    _die_if_loop_dead()
    loop = get_worker_loop()
    ctx = contextvars.copy_context()
    fut: concurrent.futures.Future[T] = concurrent.futures.Future()

    def _schedule() -> None:
        def _on_done(t: asyncio.Task) -> None:
            if t.cancelled():
                fut.cancel()
            elif (exc := t.exception()) is not None:
                fut.set_exception(exc)
            else:
                fut.set_result(t.result())

        def _create() -> None:
            # Task.__init__ calls copy_context() on the *current* context,
            # so creating the task inside ctx.run() propagates all ContextVars
            # (including current_tenant_id) into the coroutine.  This works on
            # Python 3.10; the create_task(context=) kwarg only exists on 3.11+.
            async def _run() -> T:
                return await coro_factory()

            loop.create_task(_run()).add_done_callback(_on_done)

        ctx.run(_create)

    loop.call_soon_threadsafe(_schedule)

    # Poll so we can detect thread death while a task is in flight.
    while True:
        try:
            return fut.result(timeout=_POLL_INTERVAL)
        except concurrent.futures.TimeoutError:
            _die_if_loop_dead()

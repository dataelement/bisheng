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
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_lock = threading.Lock()

_last_loop_tick = 0.0
_last_stall_warning = 0.0
_waiting_tasks = 0
_metrics_lock = threading.Lock()
_STALL_WARNING_SECONDS = 5.0

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
            _loop.call_soon_threadsafe(_tick_loop, _loop)
            logger.debug("Celery async event-loop thread started (tid=%d)", _loop_thread.ident)
        assert _loop is not None
        from bisheng.utils.async_utils import set_preferred_bridge_loop

        set_preferred_bridge_loop(_loop)
    return _loop


def _tick_loop(loop) -> None:
    global _last_loop_tick
    _last_loop_tick = time.monotonic()
    loop.call_later(1.0, _tick_loop, loop)


def get_worker_async_metrics() -> dict:
    with _metrics_lock:
        waiting = _waiting_tasks
    return {
        "waiting_tasks": waiting,
        "loop_lag_seconds": max(0.0, time.monotonic() - _last_loop_tick - 1.0) if _last_loop_tick else 0.0,
    }


def _warn_if_loop_stalled() -> None:
    global _last_stall_warning
    metrics = get_worker_async_metrics()
    now = time.monotonic()
    if metrics["loop_lag_seconds"] >= _STALL_WARNING_SECONDS and now - _last_stall_warning >= 30:
        _last_stall_warning = now
        logger.warning(
            "Celery 异步循环长时间未推进 lag=%.2fs waiting=%d", metrics["loop_lag_seconds"], metrics["waiting_tasks"]
        )


def _die_if_loop_dead() -> None:
    if _loop_thread is not None and not _loop_thread.is_alive():
        logger.critical(
            "Celery async event-loop thread has died — calling os._exit(1) "
            "so the process supervisor can restart this worker."
        )
        os._exit(1)


def run_async_task(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    timeout: float | None = None,
    cancel_grace: float = 1.0,
) -> T:
    """同步等待共享循环结果，可选超时会请求取消并有限等待清理。"""
    global _waiting_tasks
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_async_task cannot run on an event-loop thread; await the async API")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")
    if cancel_grace < 0:
        raise ValueError("cancel_grace must be nonnegative")
    _die_if_loop_dead()
    loop = get_worker_loop()
    ctx = contextvars.copy_context()
    fut: concurrent.futures.Future[T] = concurrent.futures.Future()
    cancel_requested = threading.Event()
    finished = threading.Event()
    task_holder = []

    def _schedule() -> None:
        def _on_done(task: asyncio.Task) -> None:
            try:
                if task.cancelled():
                    fut.cancel()
                elif (exc := task.exception()) is not None:
                    fut.set_exception(exc)
                else:
                    fut.set_result(task.result())
            finally:
                finished.set()

        def _create() -> None:
            if cancel_requested.is_set():
                fut.cancel()
                finished.set()
                return

            async def _run() -> T:
                return await coro_factory()

            task = loop.create_task(_run())
            task_holder.append(task)
            task.add_done_callback(_on_done)

        ctx.run(_create)

    def _cancel() -> None:
        if task_holder:
            task_holder[0].cancel()

    started = time.monotonic()
    deadline = started + timeout if timeout is not None else None
    next_warning = started + 60
    with _metrics_lock:
        _waiting_tasks += 1
    try:
        loop.call_soon_threadsafe(_schedule)
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                return fut.result(timeout=_POLL_INTERVAL if remaining is None else min(_POLL_INTERVAL, remaining))
            except concurrent.futures.TimeoutError:
                # 已完成的业务超时必须透传，不能当成轮询超时。
                if fut.done():
                    return fut.result()
                _die_if_loop_dead()
                _warn_if_loop_stalled()
                now = time.monotonic()
                if now >= next_warning:
                    logger.warning("Celery 异步任务仍在等待 elapsed=%.2fs", now - started)
                    next_warning = now + 60
                if deadline is not None and now >= deadline:
                    cancel_requested.set()
                    loop.call_soon_threadsafe(_cancel)
                    if not finished.wait(cancel_grace):
                        logger.warning("Celery 异步取消尚未完成，外部操作可能仍在执行")
                    raise concurrent.futures.TimeoutError("Celery async task wait deadline exceeded")
    finally:
        with _metrics_lock:
            _waiting_tasks -= 1

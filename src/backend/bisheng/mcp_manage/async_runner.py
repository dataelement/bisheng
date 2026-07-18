from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

from loguru import logger

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_lock = threading.Lock()


def _get_mcp_loop() -> asyncio.AbstractEventLoop:
    global _loop, _loop_thread
    with _lock:
        if _loop is None or _loop.is_closed() or _loop_thread is None or not _loop_thread.is_alive():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(
                target=_run_loop,
                args=(_loop,),
                daemon=True,
                name="bisheng-mcp-async",
            )
            _loop_thread.start()
            logger.debug("MCP async event-loop thread started")
        return _loop


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def run_mcp_async_task(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Run an MCP coroutine from sync tool execution without closing its loop."""
    loop = _get_mcp_loop()
    ctx = contextvars.copy_context()
    future: concurrent.futures.Future[T] = concurrent.futures.Future()

    def _schedule() -> None:
        def _on_done(task: asyncio.Task) -> None:
            if task.cancelled():
                future.cancel()
            elif (exc := task.exception()) is not None:
                future.set_exception(exc)
            else:
                future.set_result(task.result())

        def _create_task() -> None:
            async def _run() -> T:
                return await coro_factory()

            loop.create_task(_run()).add_done_callback(_on_done)

        ctx.run(_create_task)

    loop.call_soon_threadsafe(_schedule)
    return future.result()

"""Bounded, best-effort batching shared by the Open API write-behind paths.

Extracted verbatim from ``OpenApiCallAuditService`` when the model protocol face
needed the same machinery for a second table (design D9). Behaviour is
unchanged; the only new thing is the write callback being a parameter.

Best-effort is deliberate but never silent: a full queue or a failed batch logs
at error level and emits a metric, because a dropped row is invisible otherwise.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Generic, TypeVar

from loguru import logger

T = TypeVar("T")

SHUTDOWN_TIMEOUT_SECONDS = 5.0


class BatchedRecordWriter(Generic[T]):
    """Queue rows from the request path; flush them from one background task."""

    def __init__(
        self,
        *,
        name: str,
        write_batch: Callable[[list[T]], Awaitable[None]],
        max_queue_size: int,
        batch_size: int,
        flush_interval_seconds: float,
        log_event: str,
    ) -> None:
        self.queue: asyncio.Queue[T] = asyncio.Queue(maxsize=max_queue_size)
        self.name = name
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self._write_batch_callback = write_batch
        self._log_event = log_event
        self._task: asyncio.Task | None = None
        self._stopping = False

    def enqueue(self, entry: T) -> bool:
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._report_drop("queue_full", 1)
            return False
        return True

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name=self.name)

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        if task is None:
            await self.flush_now()
            return
        try:
            await asyncio.wait_for(task, timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            self._report_drop("shutdown_timeout", self.queue.qsize())
        finally:
            self._task = None

    async def flush_now(self) -> int:
        batch = self._drain_batch()
        if not batch:
            return 0
        await self._write_batch(batch)
        return len(batch)

    async def _run(self) -> None:
        while not self._stopping or not self.queue.empty():
            if self.queue.empty():
                try:
                    first = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=self.flush_interval_seconds,
                    )
                except TimeoutError:
                    continue
                batch = [first, *self._drain_batch(self.batch_size - 1)]
            else:
                batch = self._drain_batch()
            await self._write_batch(batch)

    def _drain_batch(self, limit: int | None = None) -> list[T]:
        remaining = self.batch_size if limit is None else max(limit, 0)
        batch: list[T] = []
        while remaining and not self.queue.empty():
            batch.append(self.queue.get_nowait())
            remaining -= 1
        return batch

    async def _write_batch(self, batch: list[T]) -> None:
        try:
            await self._write_batch_callback(batch)
        except Exception:
            logger.opt(exception=True).error(
                "{} | reason=batch_insert batch_size={}",
                self._log_event,
                len(batch),
            )
            self._on_drop(len(batch))
        finally:
            for _entry in batch:
                self.queue.task_done()

    def _report_drop(self, reason: str, count: int) -> None:
        logger.error(
            "{} | reason={} queue_size={}",
            self._log_event,
            reason,
            self.queue.qsize(),
        )
        self._on_drop(count)

    def _on_drop(self, count: int) -> None:
        """Hook for subclasses that also emit a metric for dropped rows."""


__all__ = ["SHUTDOWN_TIMEOUT_SECONDS", "BatchedRecordWriter"]

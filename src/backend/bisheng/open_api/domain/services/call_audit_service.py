"""Bounded, best-effort batching for per-call Open API audit records."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from loguru import logger

from bisheng.database.models.audit_log import AuditLog, AuditLogDao

AUDIT_QUEUE_MAX_SIZE = 1000
AUDIT_BATCH_SIZE = 100
AUDIT_FLUSH_INTERVAL_SECONDS = 1.0
AUDIT_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class OpenApiCallAuditService:
    def __init__(
        self,
        *,
        max_queue_size: int = AUDIT_QUEUE_MAX_SIZE,
        batch_size: int = AUDIT_BATCH_SIZE,
        flush_interval_seconds: float = AUDIT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self.queue: asyncio.Queue[AuditLog] = asyncio.Queue(maxsize=max_queue_size)
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    def enqueue(self, entry: AuditLog) -> bool:
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            logger.error(
                "open_api.audit.write_failed | reason=queue_full queue_size={}",
                self.queue.qsize(),
            )
            return False
        return True

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="open-api-call-audit-flusher")

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        if task is None:
            await self.flush_now()
            return
        try:
            await asyncio.wait_for(task, timeout=AUDIT_SHUTDOWN_TIMEOUT_SECONDS)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            logger.error(
                "open_api.audit.write_failed | reason=shutdown_timeout queue_size={}",
                self.queue.qsize(),
            )
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

    def _drain_batch(self, limit: int | None = None) -> list[AuditLog]:
        remaining = self.batch_size if limit is None else max(limit, 0)
        batch: list[AuditLog] = []
        while remaining and not self.queue.empty():
            batch.append(self.queue.get_nowait())
            remaining -= 1
        return batch

    async def _write_batch(self, batch: list[AuditLog]) -> None:
        try:
            await AuditLogDao.ainsert_audit_logs(batch)
        except Exception:
            logger.opt(exception=True).error(
                "open_api.audit.write_failed | reason=batch_insert batch_size={}",
                len(batch),
            )
        finally:
            for _entry in batch:
                self.queue.task_done()


open_api_call_audit_service = OpenApiCallAuditService()


__all__ = [
    "AUDIT_BATCH_SIZE",
    "AUDIT_FLUSH_INTERVAL_SECONDS",
    "AUDIT_QUEUE_MAX_SIZE",
    "OpenApiCallAuditService",
    "open_api_call_audit_service",
]

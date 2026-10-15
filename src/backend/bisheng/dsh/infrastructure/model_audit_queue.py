"""Finite process-local best-effort queues; never ACK persistence to callers."""

import asyncio
from collections import deque

from loguru import logger

from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


class BoundedAuditQueue:
    def __init__(self, *, max_events, max_bytes, consumer):
        self.max_events, self.max_bytes, self.consumer = max_events, max_bytes, consumer
        self.events = deque()
        self.used_bytes = 0
        self.closed = False
        self.wakeup = asyncio.Event()
        self.worker = None
        self.rejected = 0

    def put(self, event):
        cost = (
            len(event.body or b"")
            + 4096
            + sum(len(value.encode("utf8")) for value in event.metadata.values() if isinstance(value, str))
        )
        if self.closed or len(self.events) >= self.max_events or self.used_bytes + cost > self.max_bytes:
            self.rejected += 1
            record_audit_metric("buffer_rejected", tenant_id=event.tenant_id, kind=event.kind)
            return False
        self.events.append((event, cost))
        self.used_bytes += cost
        self.wakeup.set()
        if self.worker is None:
            self.worker = asyncio.create_task(self._run())
        return True

    async def _run(self):
        while not self.closed or self.events:
            if not self.events:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            event, cost = self.events.popleft()
            try:
                await self.consumer(event)
            except Exception as error:
                # The audit queue is optional and never propagates to model callers.
                logger.warning("DSH audit consumer unavailable ({})", type(error).__name__)
            finally:
                self.used_bytes -= cost

    async def close(self, timeout):
        self.closed = True
        self.wakeup.set()
        if self.worker is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self.worker), timeout)
        except TimeoutError:
            logger.warning("DSH audit shutdown deadline exceeded; {} buffered events abandoned", len(self.events))
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.events.clear()
            self.used_bytes = 0

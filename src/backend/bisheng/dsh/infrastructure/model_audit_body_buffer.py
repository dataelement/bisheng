"""Request-sized body jobs with one budget for active, queued and in-flight data."""

import asyncio
from collections import deque
from dataclasses import dataclass, field, replace

from loguru import logger

from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


@dataclass(eq=False, slots=True)
class AuditBodyBuffer:
    owner: "BoundedAuditBodies"
    template: AuditEvent = field(repr=False)
    fragments: list = field(default_factory=list, repr=False)
    cost: int = 0
    submitted: bool = False
    released: bool = False

    def append(self, channel, sequence, unit_index, block):
        # Charge Python object/list/index overhead, not just the serialized bytes.
        cost = len(block) + 512
        if self.released or self.submitted or not self.owner.reserve(cost):
            return False
        self.cost += cost
        self.fragments.append((channel, sequence, unit_index, block))
        return True

    def submit(self, observed_at):
        self.template = replace(self.template, observed_at=observed_at)
        return self.owner.submit(self)

    def events(self):
        for channel, sequence, unit_index, block in self.fragments:
            yield replace(
                self.template, kind="body", channel=channel, sequence=sequence, unit_index=unit_index, body=block
            )


class BoundedAuditBodies:
    def __init__(self, *, max_requests, max_bytes, consumer):
        self.max_requests, self.max_bytes, self.consumer = max_requests, max_bytes, consumer
        self.buffers = set()
        self.pending = deque()
        self.used_bytes = 0
        self.closed = False
        self.worker = None
        self.wakeup = asyncio.Event()

    def reserve(self, cost):
        if self.closed or self.used_bytes + cost > self.max_bytes:
            return False
        self.used_bytes += cost
        return True

    def open(self, template):
        cost = 4096 + sum(len(v.encode("utf8")) for v in template.metadata.values() if isinstance(v, str))
        if len(self.buffers) >= self.max_requests or not self.reserve(cost):
            record_audit_metric("buffer_rejected", tenant_id=template.tenant_id, kind="body")
            return None
        buffer = AuditBodyBuffer(self, template, cost=cost)
        self.buffers.add(buffer)
        return buffer

    def submit(self, buffer):
        if self.closed or buffer.released:
            self.release(buffer)
            return False
        if buffer.submitted:
            return True
        buffer.submitted = True
        self.pending.append(buffer)
        self.wakeup.set()
        if self.worker is None:
            try:
                self.worker = asyncio.get_running_loop().create_task(self._run())
            except Exception:
                self.pending.pop()
                self.release(buffer)
                raise
        return True

    def release(self, buffer):
        if not buffer.released:
            buffer.released = True
            self.used_bytes -= buffer.cost
            buffer.fragments.clear()
            self.buffers.discard(buffer)

    async def _run(self):
        while not self.closed or self.pending:
            if not self.pending:
                self.wakeup.clear()
                await self.wakeup.wait()
                continue
            buffer = self.pending.popleft()
            try:
                await self.consumer(buffer)
            except Exception as error:
                logger.warning("DSH audit body job unavailable ({})", type(error).__name__)
                record_audit_metric("body_job_failed", tenant_id=buffer.template.tenant_id)
            finally:
                self.release(buffer)

    async def close(self, timeout):
        self.closed = True
        self.wakeup.set()
        try:
            if self.worker is not None:
                await asyncio.wait_for(asyncio.shield(self.worker), timeout)
        except TimeoutError:
            logger.warning("DSH audit body shutdown deadline exceeded")
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        finally:
            self.pending.clear()
            for buffer in tuple(self.buffers):
                self.release(buffer)

"""Bounded per-user Stream projection, commit-before-ACK, and orphan inspection."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from loguru import logger
from redis.exceptions import ResponseError

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis, QuotaRejected


class DshProjectionService:
    group = "dsh-sql-projection-v1"

    def __init__(
        self,
        quota: QuotaRedis,
        repository_scope: Callable[[], AbstractContextManager[DshUsageRepository]],
        *,
        consumer: str,
        claim_idle_ms: int = 60000,
        backpressure_seconds: int = 30,
        high_watermark: int = 10000,
        retention_seconds: int = 2592000,
        max_batches: int = 10,
        max_seconds: float = 1.0,
    ):
        if not consumer or min(claim_idle_ms, backpressure_seconds, high_watermark) < 1:
            raise ValueError("Projection requires a named consumer and positive bounds")
        self.retention_seconds, self.max_batches, self.max_seconds = retention_seconds, max_batches, max_seconds
        self.quota, self.repository_scope, self.consumer = quota, repository_scope, consumer
        self.claim_idle_ms, self.backpressure_seconds, self.high_watermark = (
            claim_idle_ms,
            backpressure_seconds,
            high_watermark,
        )

    def _base(self, tenant_id: int, user_id: int):
        if tenant_id != get_current_tenant_id() or user_id < 1:
            raise ValueError("Projection scope must match trusted worker tenant context")
        return f"{self.quota.prefix}:{{{tenant_id}:{user_id}}}"

    async def project_batch(self, tenant_id: int, user_id: int) -> int:
        base = self._base(tenant_id, user_id)
        redis = self.quota.redis
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            if not await redis.exists(base + ":events"):
                return 0
            try:
                await redis.xgroup_create(base + ":events", self.group, id="0-0")
            except ResponseError as exc:
                if not str(exc).startswith("BUSYGROUP"):
                    raise
            await self._backpressure(base)
            claimed = await redis.xautoclaim(
                base + ":events", self.group, self.consumer, self.claim_idle_ms, start_id="0-0", count=500
            )
            records = claimed[1]
            if len(claimed) > 2 and claimed[2]:
                await redis.hset(base + ":gate", "state", "FROZEN")
                raise QuotaRejected("pending_events_lost")
            if not records:
                pending = await redis.xreadgroup(self.group, self.consumer, {base + ":events": "0"}, count=500)
                records = pending[0][1] if pending else []
            if not records:
                fresh = await redis.xreadgroup(self.group, self.consumer, {base + ":events": ">"}, count=500)
                records = fresh[0][1] if fresh else []
        if not records:
            return 0
        events = []
        for _, fields in records:
            event = UsageEvent.model_validate_json(fields["event"])
            if event.tenant_id != tenant_id or event.user_id != user_id:
                await redis.hset(base + ":gate", "state", "FROZEN")
                raise ValueError("Stream event ownership does not match its user partition")
            events.append(event)
        with self.repository_scope() as repository:
            repository.project_batch(events)
        # Exiting the scope above must have committed successfully; ACK is intentionally later.
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            # Record exact SQL confirmation after commit, then ACK; pending entries cannot be deleted.
            await redis.eval(
                (Path(__file__).parents[2] / "infrastructure/lua/confirm_projection.lua").read_text(),
                len(records) + 1,
                base + ":events",
                *[base + ":request:" + event.request_id for event in events],
                self.group,
                *[item for record in records for item in (record[0], record[1]["event"])],
            )
            await redis.xack(base + ":events", self.group, *[record[0] for record in records])
            await self._backpressure(base)
        return len(records)

    async def _backpressure(self, base: str):
        redis = self.quota.redis
        group = next(row for row in await redis.xinfo_groups(base + ":events") if row["name"] == self.group)
        lag = group.get("lag")
        if lag is None:
            await redis.hset(base + ":gate", "backpressure", "1")
            return  # Continue draining while admission remains closed; trimming can make Redis lag unknown.
        pending = await redis.xpending_range(base + ":events", self.group, "-", "+", 1)
        unread = await redis.xrange(base + ":events", min="(" + group["last-delivered-id"], max="+", count=1)
        ids = ([pending[0]["message_id"]] if pending else []) + ([unread[0][0]] if unread else [])
        now = await redis.time()
        now_ms = now[0] * 1000 + now[1] // 1000
        age = max([now_ms - int(message_id.split("-")[0]) for message_id in ids], default=0)
        blocked = lag + group["pending"] >= self.high_watermark or age > self.backpressure_seconds * 1000
        await redis.hset(base + ":gate", "backpressure", "1" if blocked else "0")

    async def inspect_running(
        self, tenant_id: int, user_id: int, *, now: datetime, timeout_seconds: int, cursor: int = 0
    ) -> tuple[int, int]:
        base = self._base(tenant_id, user_id)
        if now.tzinfo is None or timeout_seconds < 1:
            raise ValueError("Inspection requires an aware clock and a positive upstream timeout")
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            if await self.quota.redis.hget(base + ":gate", "running_index") != "1":
                raise QuotaRejected("running_index_missing")
            expected = await self.quota.redis.hget(base + ":gate", "running_count")
            if expected is None or int(expected) != await self.quota.redis.zcard(base + ":running"):
                raise QuotaRejected("running_index_missing")
            cutoff = int((now.timestamp() - timeout_seconds) * 1000)
            ids = await self.quota.redis.zrangebyscore(base + ":running", "-inf", cutoff, start=0, num=100)
            values = [await self.quota.redis.hget(base + ":request:" + request_id, "event") for request_id in ids]
            next_cursor = 1 if len(ids) == 100 else 0
        changed = 0
        for value in values:
            if value is None:
                raise QuotaRejected("missing_request_ledger")
            event = UsageEvent.model_validate_json(value)
            if event.tenant_id != tenant_id or event.user_id != user_id:
                raise ValueError("Request ownership mismatch during inspection")
            started = event.started_at.replace(tzinfo=UTC) if event.started_at.tzinfo is None else event.started_at
            if event.status == "RUNNING" and (now - started).total_seconds() > timeout_seconds:
                unknown = event.model_copy(
                    update={
                        "event_version": event.event_version + 1,
                        "status": "USAGE_UNKNOWN",
                        "error_code": "interrupted_unknown",
                    }
                )
                try:
                    await self.quota.record_usage(unknown, event.event_version)
                    changed += 1
                except QuotaRejected as exc:
                    if exc.reason not in {"event_version_conflict", "settlement_conflict", "already_settled"}:
                        raise
                    # A concurrent terminal settlement won the CAS; no retry or model replay.
                    logger.info("DSH inspection observed concurrent settlement request={}", event.request_id)
        return next_cursor, changed

    async def cleanup_batch(self, tenant_id: int, user_id: int, *, retention_seconds: int | None = None) -> int:
        base = self._base(tenant_id, user_id)
        retention = self.retention_seconds if retention_seconds is None else retention_seconds
        if retention < 1:
            raise ValueError("Cleanup requires a positive retention period")
        redis = self.quota.redis
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            cursor = await redis.hget(base + ":gate", "cleanup_cursor") or "-"
            records = await redis.xrange(base + ":events", min=cursor, max="+", count=100)
            script = (Path(__file__).parents[2] / "infrastructure/lua/cleanup.lua").read_text()
            deleted = 0
            for stream_id, fields in records:
                event = UsageEvent.model_validate_json(fields["event"])
                if event.tenant_id != tenant_id or event.user_id != user_id:
                    raise QuotaRejected("cleanup_ownership_mismatch")
                key = base + ":request:" + event.request_id
                value = await redis.hget(key, "event")
                if value:
                    deleted += await redis.eval(
                        script, 2, base + ":events", key, self.group, stream_id, value, str(retention * 1000)
                    )
            await redis.hset(base + ":gate", "cleanup_cursor", "(" + records[-1][0] if len(records) == 100 else "-")
            return deleted

    async def drain_user(
        self, tenant_id: int, user_id: int, *, max_batches: int | None = None, max_seconds: float | None = None
    ) -> tuple[int, bool]:
        """Each user gets bounded work, then yields to the queue; a lease prevents replica overlap."""
        base = self._base(tenant_id, user_id)
        batches = self.max_batches if max_batches is None else max_batches
        seconds = self.max_seconds if max_seconds is None else max_seconds
        if batches < 1 or seconds <= 0:
            raise ValueError("Drain requires positive bounds")
        owner = uuid4().hex
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            if not await self.quota.redis.set(base + ":projection_lease", owner, nx=True, px=30000):
                return 0, False
        total, start = 0, monotonic()
        try:
            for _ in range(batches):
                count = await self.project_batch(tenant_id, user_id)
                total += count
                if count < 500 or monotonic() - start >= seconds:
                    break
                # Renew only our lease; a slow SQL transaction may have outlived it.
                alive = await self.quota.redis.eval(
                    "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('PEXPIRE',KEYS[1],30000) end return 0",
                    1,
                    base + ":projection_lease",
                    owner,
                )
                if not alive:
                    return total, False
            await self.cleanup_batch(tenant_id, user_id)
            async with self.quota.topology.lock:
                await self.quota.topology.check()
                groups = await self.quota.redis.xinfo_groups(base + ":events")
                group = next((row for row in groups if row["name"] == self.group), None)
                # Fresh backlog can continue now. PEL owned by another process waits for normal reclaim age.
                more = group is not None and group.get("lag") != 0
                return total, more
        finally:
            await self.quota.redis.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                1,
                base + ":projection_lease",
                owner,
            )

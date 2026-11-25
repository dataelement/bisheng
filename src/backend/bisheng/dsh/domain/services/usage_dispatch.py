"""Bounded projection batches and low-frequency repair, without per-user Celery fan-out."""

import re
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from loguru import logger
from redis.exceptions import RedisError

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.dsh.infrastructure.usage_work import UsageWorkQueue


class UsageDispatcher:
    def __init__(self, projection):
        self.projection = projection
        self.quota = projection.quota
        self.work = UsageWorkQueue(self.quota)

    def partition(self, stream):
        match = re.fullmatch(re.escape(self.quota.prefix) + r":\{([1-9][0-9]*):([1-9][0-9]*)\}:events", stream)
        if match is None:
            raise ValueError("Malformed quota stream partition")
        return tuple(map(int, match.groups()))

    async def dispatch(self, *, max_users=16, max_seconds=4):
        started, users, events = monotonic(), 0, 0
        while users < max_users and monotonic() - started < max_seconds:
            claim = await self.work.claim()
            if not claim:
                break
            stream = claim[0]
            tenant, user = self.partition(stream)
            try:
                retry_tool_settlement = False
                with profile_scope(tenant):
                    try:
                        await self.quota.replay_tool_settlements(tenant, user)
                    except (QuotaRejected, RedisError):
                        # 已持久化的工具结算继续重试。现有事件仍可投影。
                        retry_tool_settlement = True
                        logger.exception("DSH tool settlement pending tenant={} user={}", tenant, user)
                    count, more = await self.projection.drain_user(tenant, user)
                async with self.quota.topology.lock:
                    await self.quota.topology.check()
                    groups = (
                        await self.quota.redis.xinfo_groups(stream) if await self.quota.redis.exists(stream) else []
                    )
                    pending = next((g["pending"] for g in groups if g["name"] == self.projection.group), 0)
                # Unknown lag never drives scheduling. Pending entries wait for reclaim eligibility.
                delay = 2000 if more else max(2000, self.projection.claim_idle_ms) if pending else 0
                if retry_tool_settlement:
                    delay = min(delay, 30000) if delay else 30000
                await self.work.finish(claim, retry_ms=delay)
                events += count
            except Exception:
                logger.exception("DSH usage projection failed tenant={} user={}; work retained for retry", tenant, user)
                await self.work.finish(claim, retry_ms=30000, failed=True)
            users += 1
        logger.debug("DSH usage batch users={} events={} duration={:.3f}s", users, events, monotonic() - started)
        return events

    async def repair(self):
        """Inspect registered partitions only; unrelated Redis keys never affect the sweep."""
        redis = self.quota.redis
        lease, owner = self.quota.prefix + ":usage_repair_lease", uuid4().hex
        cursor_key = self.quota.prefix + ":usage_repair_cursor"
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            if not await redis.set(lease, owner, nx=True, px=60000):
                return 0
        try:
            async with self.quota.topology.lock:
                await self.quota.topology.check()
                cursor = int(await redis.get(cursor_key) or 0)
                next_cursor, streams = await redis.sscan(self.work.partitions, cursor, count=100)
            for stream in streams:
                tenant, user = self.partition(stream)
                base = stream.removesuffix(":events")
                async with self.quota.topology.lock:
                    await self.quota.topology.check()
                    pending_tool = await redis.exists(base + ":tool_settlements")
                    is_stream = await redis.type(stream) == "stream"
                    groups = await redis.xinfo_groups(stream) if is_stream else []
                    group = next((g for g in groups if g["name"] == self.projection.group), None)
                    unread = is_stream and (
                        group is None
                        or bool(await redis.xrange(stream, min="(" + group["last-delivered-id"], max="+", count=1))
                    )
                    running = await redis.zcard(base + ":running") if is_stream else 0
                if pending_tool or unread or (group is not None and group["pending"]):
                    await self.work.mark(stream)
                if not is_stream:
                    continue
                with profile_scope(tenant):
                    if running:
                        await self.projection.inspect_running(tenant, user, now=datetime.now(UTC), timeout_seconds=3600)
                    await self.projection.cleanup_batch(tenant, user)
            # Commit the cursor only while still owning the scan. Failure retries the same page.
            await redis.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then redis.call('SET',KEYS[2],ARGV[2]); return 1 end return 0",
                2,
                lease,
                cursor_key,
                owner,
                next_cursor,
            )
            return len(streams)
        finally:
            await redis.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                1,
                lease,
                owner,
            )

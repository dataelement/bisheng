"""Bounded projection batches and low-frequency repair, without per-user Celery fan-out."""

import re
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from loguru import logger

from bisheng.dsh.domain.services.profile import profile_scope
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
                with profile_scope(tenant):
                    count, more = await self.projection.drain_user(tenant, user)
                async with self.quota.topology.lock:
                    await self.quota.topology.check()
                    groups = (
                        await self.quota.redis.xinfo_groups(stream) if await self.quota.redis.exists(stream) else []
                    )
                    pending = next((g["pending"] for g in groups if g["name"] == self.projection.group), 0)
                # Unknown lag never drives scheduling. Pending entries wait for reclaim eligibility.
                delay = 2000 if more else max(2000, self.projection.claim_idle_ms) if pending else 0
                await self.work.finish(claim, retry_ms=delay)
                events += count
            except Exception:
                logger.exception("DSH usage projection failed tenant={} user={}; work retained for retry", tenant, user)
                await self.work.finish(claim, retry_ms=30000, failed=True)
            users += 1
        logger.debug("DSH usage batch users={} events={} duration={:.3f}s", users, events, monotonic() - started)
        return events

    async def bootstrap(self, *, max_pages=20, max_seconds=0.25):
        """Discover pre-index streams once per Redis generation, with resumable bounded work.

        New writes atomically register their partition. Normal dispatch and repair
        never enumerate the database after this compatibility pass completes.
        """
        redis = self.quota.redis
        base = self.quota.prefix + ":usage_inventory"
        lease, cursor_key, done = base + ":lease", base + ":cursor", base + ":generation"
        owner = uuid4().hex
        async with self.quota.topology.lock:
            await self.quota.topology.check()
            generation = self.quota.topology.run_id
            if await redis.get(done) == generation:
                return True
            if not await redis.set(lease, owner, nx=True, px=60000):
                return False
            # A restored Redis may have a different hash-table layout. An old
            # unfinished SCAN cursor is not valid evidence for the new primary.
            if await redis.get(base + ":cursor_generation") != generation:
                await redis.set(cursor_key, 0)
                await redis.set(base + ":cursor_generation", generation)
        try:
            started = monotonic()
            for _ in range(max_pages):
                async with self.quota.topology.lock:
                    await self.quota.topology.check()
                    cursor = int(await redis.get(cursor_key) or 0)
                    next_cursor, streams = await redis.scan(cursor, match=self.quota.prefix + ":*:events", count=500)
                for stream in streams:
                    self.partition(stream)
                    await self.work.mark(stream)
                committed = await redis.eval(
                    "if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end "
                    "redis.call('SET',KEYS[2],ARGV[2]); "
                    "if ARGV[2]=='0' then redis.call('SET',KEYS[3],ARGV[3]) end; return 1",
                    3,
                    lease,
                    cursor_key,
                    done,
                    owner,
                    next_cursor,
                    generation,
                )
                if not committed:
                    return False
                if not next_cursor:
                    return True
                if monotonic() - started >= max_seconds:
                    break
            return False
        finally:
            await redis.eval(
                "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                1,
                lease,
                owner,
            )

    async def repair(self):
        """Inspect registered partitions only; unrelated Redis keys never affect the sweep."""
        await self.bootstrap()
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
                async with self.quota.topology.lock:
                    await self.quota.topology.check()
                    if not await redis.exists(stream):
                        continue
                    groups = await redis.xinfo_groups(stream)
                    group = next((g for g in groups if g["name"] == self.projection.group), None)
                    unread = group is None or bool(
                        await redis.xrange(stream, min="(" + group["last-delivered-id"], max="+", count=1)
                    )
                    running = await redis.zcard(stream.removesuffix(":events") + ":running")
                if unread or (group is not None and group["pending"]):
                    await self.work.mark(stream)
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

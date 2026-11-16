"""Exact topology reads and bounded writes for operational department recovery."""

import asyncio
import math
import time

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.permission.application.sql_runtime import (
    RECENT_MARKER_PREFIX,
    RECENT_MARKER_SENTINEL,
    FGAProjectionAdapter,
)
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryRuntimeError,
)


class RecoveryRequestLimiter:
    def __init__(self, qps=2.0):
        if not math.isfinite(qps) or qps <= 0:
            raise ValueError("max-fga-qps must be positive")
        self.interval = 1.0 / qps
        self.last = 0.0
        self.calls = 0
        self.wait_seconds = 0.0
        self._lock = asyncio.Lock()

    async def on_request(self, request):
        async with self._lock:
            delay = self.last + self.interval - time.monotonic()
            waited = 0.0
            if delay > 0:
                started = time.monotonic()
                await asyncio.sleep(delay)
                waited = time.monotonic() - started
            self.wait_seconds += waited
            from bisheng.core.database.query_statistics import record_external_request

            record_external_request("fga", waited)
            self.last = time.monotonic()
            self.calls += 1


class DepartmentRecoveryFGA:
    def __init__(self, client, *, marker_window=120, redis_factory=get_redis_client):
        self.client = client
        self.marker_window = marker_window
        self.redis_factory = redis_factory

    async def write(self, deltas):
        async with asyncio.timeout(5):
            return await FGAProjectionAdapter(self.client).write_atomic(
                writes=tuple(delta for delta in deltas if delta.action == "WRITE"),
                deletes=tuple(delta for delta in deltas if delta.action == "DELETE"),
            )

    async def ready(self):
        redis = await self.redis_factory()
        return await redis.aget(RECENT_MARKER_SENTINEL) == "ready"

    async def arm(self, plan):
        # Never call RedisConsistencyMarker.is_ready(): it can start sentinel recovery.
        redis = await self.redis_factory()
        if await redis.aget(RECENT_MARKER_SENTINEL) != "ready":
            raise RecoveryRuntimeError("CONSISTENCY_MARKER_NOT_READY")
        await redis.aset(
            f"{RECENT_MARKER_PREFIX}:{plan.tenant_id}:*",
            plan.idempotency_key,
            expiration=self.marker_window,
        )
        if await redis.aget(RECENT_MARKER_SENTINEL) != "ready":
            raise RecoveryRuntimeError("CONSISTENCY_MARKER_CHANGED")

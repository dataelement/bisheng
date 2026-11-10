"""AC-13/AC-24/AC-37: token-independent leases and generation protection."""

import asyncio
from unittest.mock import AsyncMock

from bisheng.dsh.infrastructure.model_audit_activity import RedisAuditActivity


class LeaseRedis:
    def __init__(self):
        self.values = {}
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.delay = False
        self.refreshes = 0

    async def set(self, key, generation, **_kwargs):
        self.started.set()
        if self.delay:
            await self.release.wait()
        self.values.setdefault(key, generation)

    async def exists(self, key):
        return key in self.values

    async def eval(self, _script, _count, key, generation, *ttl):
        if self.values.get(key) != generation:
            return 0
        if ttl:
            self.refreshes += 1
        else:
            self.values.pop(key)
        return 1


async def test_finished_before_delayed_initial_set_does_not_leave_a_false_active_lease():
    redis = LeaseRedis()
    redis.delay = True
    activity = RedisAuditActivity(redis, interval=0.1, maximum=1, observation_window=300)
    try:
        activity.started("request")
        await asyncio.wait_for(redis.started.wait(), 1)
        activity.finished("request")
        await asyncio.sleep(0)
        redis.release.set()
        for _ in range(100):
            await asyncio.sleep(0.001)
            if not activity.active and not await activity.confirmed("request"):
                break
        assert not await activity.confirmed("request")
    finally:
        await activity.close()


async def test_activity_refreshes_without_tokens_and_stale_finish_cannot_delete_new_generation():
    redis = LeaseRedis()
    activity = RedisAuditActivity(redis, interval=0.005, maximum=1, observation_window=300)
    try:
        activity.started("request")
        activity.started("overflow")
        assert len(activity.active) == 1
        await asyncio.wait_for(redis.started.wait(), 1)
        await asyncio.sleep(0.02)
        assert redis.refreshes > 0 and await activity.confirmed("request")
        generation = activity.active["request"][0]
        redis.values[activity.key("request")] = "new-generation"
        await activity._finish("request", generation)
        assert redis.values[activity.key("request")] == "new-generation"
    finally:
        await activity.close()


async def test_activity_check_unavailable_is_not_false():
    redis = AsyncMock()
    redis.exists.side_effect = TimeoutError()
    activity = RedisAuditActivity(redis, interval=1, maximum=1, observation_window=300)
    assert await activity.confirmed("request") is None
    await activity.close()

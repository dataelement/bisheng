import re
import subprocess
import sys

from bisheng.api_rate_limit.domain.repositories.implementations import ApiRateLimitRedisRepository
from bisheng.api_rate_limit.domain.schemas import RateLimitLimits


class _RecordingRedis:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def aeval(self, script, *, keys, args=None):
        self.calls.append((script, keys, args or []))
        return self.result


async def test_counter_uses_one_cluster_slot_and_returns_longest_exceeded_window():
    redis = _RecordingRedis([0, 1, 3600])
    repository = ApiRateLimitRedisRepository(redis)

    decision = await repository.check(
        method="GET",
        route_template="/api/v1/items/{item_id}",
        limits=RateLimitLimits(second=2, minute=20, hour=200),
        now=7200,
    )

    _script, keys, args = redis.calls[0]
    hash_tags = [re.search(r"\{[^}]+\}", key).group(0) for key in keys]
    assert len(set(hash_tags)) == 1
    assert [key.rsplit(":", 2)[-2] for key in keys] == ["hour", "minute", "second"]
    assert args == [200, 3600, 20, 60, 2, 1]
    assert not decision.allowed
    assert decision.dimension.value == "hour"
    assert decision.retry_after == 3600


def test_policy_hash_changes_only_when_effective_limits_change():
    first = RateLimitLimits(second=3, minute=20)
    same = RateLimitLimits(second=3, minute=20)
    changed = RateLimitLimits(second=4, minute=20)

    assert ApiRateLimitRedisRepository._policy_hash(first) == ApiRateLimitRedisRepository._policy_hash(same)
    assert ApiRateLimitRedisRepository._policy_hash(first) != ApiRateLimitRedisRepository._policy_hash(changed)


def test_lua_counter_contract_runs_against_fakeredis():
    script = r"""
import asyncio
from unittest.mock import AsyncMock

import fakeredis.aioredis

from bisheng.api_rate_limit.domain.repositories.implementations import ApiRateLimitRedisRepository
from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig, RateLimitLimits
from bisheng.core.cache.redis_conn import RedisClient

async def main():
    server = fakeredis.FakeServer()
    first_client = object.__new__(RedisClient)
    first_client.async_connection = fakeredis.aioredis.FakeRedis(server=server)
    first_client.acluster_nodes = AsyncMock()
    second_client = object.__new__(RedisClient)
    second_client.async_connection = fakeredis.aioredis.FakeRedis(server=server)
    second_client.acluster_nodes = AsyncMock()
    first_repository = ApiRateLimitRedisRepository(first_client)
    second_repository = ApiRateLimitRedisRepository(second_client)
    limits = RateLimitLimits(second=2, minute=10)
    first = await first_repository.check(
        method="GET", route_template="/api/v1/items/{item_id}", limits=limits, now=120,
    )
    second = await second_repository.check(
        method="GET", route_template="/api/v1/items/{item_id}", limits=limits, now=120,
    )
    third = await first_repository.check(
        method="GET", route_template="/api/v1/items/{item_id}", limits=limits, now=120,
    )
    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.dimension.value == "second"
    assert third.retry_after == 1

    config = ApiRateLimitConfig.model_validate({
        "revision": 7,
        "global": {"limits": {"minute": 8}, "message": "active config"},
    })
    candidate_key = await first_repository.stage(config)
    assert await first_repository.activate(candidate_key, config.revision) is True
    replicated_config = await second_repository.get_active()
    assert replicated_config is not None
    assert replicated_config.model_dump(mode="json", by_alias=True) == config.model_dump(
        mode="json", by_alias=True,
    )
    await first_client.async_connection.aclose()
    await second_client.async_connection.aclose()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

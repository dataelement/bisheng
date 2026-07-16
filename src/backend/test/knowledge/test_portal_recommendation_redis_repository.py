from datetime import datetime, timedelta, timezone

import pytest

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_redis_repository import (
    PortalRecommendationRedisRepositoryImpl,
)
from bisheng.knowledge.domain.services.portal_recommendation_pool_service import (
    PortalRecommendationPoolState,
)
from bisheng.knowledge.domain.services.portal_recommendation_service import (
    PortalRecommendationCandidate,
)


class _FakeAsyncRedis:
    def __init__(self):
        self.strings = {}
        self.hashes = {}
        self.zsets = {}
        self.expirations = {}
        self.fail_read_transaction = False
        self.fail_invalidate_transaction = False

    async def incr(self, key):
        value = int(self.strings.get(key, 0)) + 1
        self.strings[key] = str(value)
        return value

    async def get(self, key):
        value = self.strings.get(key)
        return None if value is None else str(value).encode()

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.strings:
            return False
        self.strings[key] = value.decode() if isinstance(value, bytes) else str(value)
        if kwargs.get("ex") is not None:
            self.expirations[key] = int(kwargs["ex"])
        return True

    async def delete(self, *keys):
        for key in keys:
            self.strings.pop(key, None)
            self.hashes.pop(key, None)
            self.zsets.pop(key, None)
        return len(keys)

    async def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True

    async def zadd(self, key, mapping, **kwargs):
        items = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            member = str(member)
            score = float(score)
            if kwargs.get("gt") and member in items and score <= items[member]:
                continue
            items[member] = score

    async def zremrangebyscore(self, key, minimum, maximum):
        items = self.zsets.setdefault(key, {})
        minimum = float("-inf") if minimum == "-inf" else float(minimum)
        maximum = float("inf") if maximum == "+inf" else float(maximum)
        for member, score in list(items.items()):
            if minimum <= score <= maximum:
                items.pop(member)

    async def zremrangebyrank(self, key, start, stop):
        ordered = sorted(self.zsets.setdefault(key, {}).items(), key=lambda item: (item[1], item[0]))
        if stop < 0:
            stop = len(ordered) + stop
        for member, _score in ordered[start : stop + 1]:
            self.zsets[key].pop(member, None)

    async def zrange(self, key, start, stop, *, desc=False, withscores=False):
        ordered = sorted(
            self.zsets.setdefault(key, {}).items(),
            key=lambda item: (item[1], item[0]),
            reverse=desc,
        )
        if stop < 0:
            stop = len(ordered) + stop
        values = ordered[start : stop + 1]
        if withscores:
            return [(member.encode(), score) for member, score in values]
        return [member.encode() for member, _score in values]

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def hgetall(self, key):
        return {field.encode(): str(value).encode() for field, value in self.hashes.get(key, {}).items()}

    async def hset(self, key, *, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    async def hincrby(self, key, field, amount):
        value = int(self.hashes.setdefault(key, {}).get(field, 0)) + amount
        self.hashes[key][field] = value
        return value

    async def eval(self, _script, numkeys, *args):
        if numkeys == 2:
            if len(args) == 2:
                if self.fail_invalidate_transaction:
                    raise RuntimeError("simulated invalidation failure")
                domains_key, behavior_key = args
                self.strings.pop(domains_key, None)
                value = int(self.strings.get(behavior_key, 0)) + 1
                self.strings[behavior_key] = str(value)
                return value
            if self.fail_read_transaction:
                raise RuntimeError("simulated transaction failure")
            reads_key, behavior_key, member, score, cutoff, ttl = args
            items = self.zsets.setdefault(reads_key, {})
            old_score = items.get(str(member))
            if old_score is None or float(score) > old_score:
                items[str(member)] = float(score)
            for old_member, old_value in list(items.items()):
                if old_value <= float(cutoff):
                    items.pop(old_member)
            self.expirations[reads_key] = int(ttl)
            value = int(self.strings.get(behavior_key, 0)) + 1
            self.strings[behavior_key] = str(value)
            return value

        key, generation, pool_version, fingerprint = args
        state = self.hashes.setdefault(key, {})
        desired = int(state.get("desired_generation", 0))
        active = int(state.get("active_generation", 0))
        generation = int(generation)
        if desired != generation or generation <= active:
            return 0
        state.update(
            {
                "active_generation": generation,
                "active_pool_version": pool_version,
                "active_fingerprint": fingerprint,
            }
        )
        return 1


class _FakeRedisClient:
    def __init__(self):
        self.async_connection = _FakeAsyncRedis()


@pytest.fixture()
def repository():
    return PortalRecommendationRedisRepositoryImpl(redis_client=_FakeRedisClient())


def test_physical_keys_keep_default_compatibility_and_prefix_non_default_tenants(repository):
    assert repository.behavior_version_key(1, 7) == "sg:rec:v1:user:{1}:7:behavior_version"
    assert repository.behavior_version_key(5, 7) == "t:5:sg:rec:v1:user:{5}:7:behavior_version"
    assert "{5}" in repository.pool_state_key(5)


def test_all_user_keys_share_the_same_tenant_cluster_hash_tag(repository):
    keys = [
        repository.behavior_version_key(5, 7),
        repository.reads_key(5, 7),
        repository.interest_key(5, 7),
        repository.domains_key(5, 7),
        repository.top_n_key(5, 7, 2, "pool-a", 3),
    ]

    assert all("{5}" in key for key in keys)


@pytest.mark.asyncio
async def test_read_zset_keeps_latest_timestamp_and_trims_ninety_days(repository):
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    token = current_tenant_id.set(5)
    try:
        await repository.record_read(5, 7, 10, 100, now - timedelta(days=100))
        await repository.record_read(5, 7, 10, 100, now - timedelta(days=1))
        await repository.record_read(5, 7, 10, 101, now)
        reads = await repository.list_recent_reads(5, 7, now=now)
    finally:
        current_tenant_id.reset(token)

    assert set(reads) == {(10, 100), (10, 101)}
    assert reads[(10, 100)] == now - timedelta(days=1)


@pytest.mark.asyncio
async def test_read_and_behavior_version_are_updated_atomically(repository):
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    token = current_tenant_id.set(5)
    try:
        version = await repository.record_read_and_increment_behavior_version(5, 7, 10, 100, now)
        reads = await repository.list_recent_reads(5, 7, now=now)
    finally:
        current_tenant_id.reset(token)

    assert version == 1
    assert reads[(10, 100)] == now


@pytest.mark.asyncio
async def test_read_transaction_failure_leaves_read_and_version_unchanged(repository):
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    repository.redis.async_connection.fail_read_transaction = True
    token = current_tenant_id.set(5)
    try:
        with pytest.raises(RuntimeError, match="simulated transaction failure"):
            await repository.record_read_and_increment_behavior_version(5, 7, 10, 100, now)
    finally:
        current_tenant_id.reset(token)

    redis = repository.redis.async_connection
    assert repository.reads_key(5, 7) not in redis.zsets
    assert repository.behavior_version_key(5, 7) not in redis.strings


@pytest.mark.asyncio
async def test_interest_is_top_fifty_and_expires_in_thirty_minutes(repository):
    token = current_tenant_id.set(5)
    try:
        await repository.replace_interest(
            5,
            7,
            [(f"10:{file_id}", float(file_id)) for file_id in range(60)],
            1800,
        )
        interests = await repository.get_interest(5, 7)
    finally:
        current_tenant_id.reset(token)

    assert len(interests) == 50
    assert interests[0] == ("10:59", 59.0)
    key = repository.interest_key(5, 7)
    assert repository.redis.async_connection.expirations[key] == 1800


@pytest.mark.asyncio
async def test_behavior_and_topn_keys_are_versioned(repository):
    token = current_tenant_id.set(5)
    try:
        assert await repository.increment_behavior_version(5, 7) == 1
        await repository.set_top_n(5, 7, 2, "pool-a", 1, [(10, 100), (10, 101)], ttl_seconds=240)
        assert await repository.get_top_n(5, 7, 2, "pool-a", 1) == [(10, 100), (10, 101)]
        assert await repository.get_top_n(5, 7, 2, "pool-a", 2) is None
    finally:
        current_tenant_id.reset(token)


@pytest.mark.asyncio
async def test_user_domain_invalidation_and_version_are_atomic(repository):
    token = current_tenant_id.set(5)
    try:
        await repository.set_user_domains(5, 7, ["SAFE"])
        await repository.invalidate_user(5, 7)
    finally:
        current_tenant_id.reset(token)

    redis = repository.redis.async_connection
    assert repository.domains_key(5, 7) not in redis.strings
    assert redis.strings[repository.behavior_version_key(5, 7)] == "1"


@pytest.mark.asyncio
async def test_user_invalidation_failure_leaves_domain_and_version_unchanged(repository):
    token = current_tenant_id.set(5)
    try:
        await repository.set_user_domains(5, 7, ["SAFE"])
        repository.redis.async_connection.fail_invalidate_transaction = True
        with pytest.raises(RuntimeError, match="simulated invalidation failure"):
            await repository.invalidate_user(5, 7)
    finally:
        current_tenant_id.reset(token)

    redis = repository.redis.async_connection
    assert repository.domains_key(5, 7) in redis.strings
    assert repository.behavior_version_key(5, 7) not in redis.strings


@pytest.mark.asyncio
async def test_active_pool_cas_only_accepts_latest_desired_generation(repository):
    token = current_tenant_id.set(5)
    try:
        first = await repository.increment_desired_generation(5)
        second = await repository.increment_desired_generation(5)
        assert (first, second) == (1, 2)
        assert not await repository.activate_pool_if_current(5, 1, "pool-old", "fp-old")
        assert await repository.activate_pool_if_current(5, 2, "pool-new", "fp-new")
        state = await repository.get_pool_state(5)
    finally:
        current_tenant_id.reset(token)

    assert state.active_generation == 2
    assert state.active_pool_version == "pool-new"
    assert state.fingerprint == "fp-new"


@pytest.mark.asyncio
async def test_versioned_pool_and_per_file_rotation_state_expire_together(repository):
    token = current_tenant_id.set(5)
    states = {
        (10, 100): PortalRecommendationPoolState(
            active_since=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
            cooldown_until=datetime(2026, 7, 18, tzinfo=timezone.utc).date(),
        )
    }
    try:
        await repository.replace_pool(
            5,
            "pool-a",
            "generic",
            [(PortalRecommendationCandidate(space_id=10, file_id=100), 1.0)],
        )
        await repository.replace_hot_rotation_states(5, "pool-a", "generic", states)
        loaded = await repository.get_hot_rotation_states(5, "pool-a", "generic")
        size = await repository.get_pool_size(5, "pool-a", "generic")
    finally:
        current_tenant_id.reset(token)

    assert loaded == states
    assert size == 1
    redis = repository.redis.async_connection
    assert redis.expirations[repository.pool_key(5, "pool-a", "generic")] == 48 * 60 * 60
    assert redis.expirations[repository.pool_key(5, "pool-a", "generic:hot_state")] == 48 * 60 * 60


@pytest.mark.asyncio
async def test_reconcile_watermark_treats_naive_database_datetime_as_utc(repository):
    naive = datetime(2026, 7, 15, 8, 30)
    token = current_tenant_id.set(5)
    try:
        await repository.set_reconcile_watermark(5, naive, 101)
        loaded = await repository.get_reconcile_watermark(5)
    finally:
        current_tenant_id.reset(token)

    assert loaded == (datetime(2026, 7, 15, 8, 30, tzinfo=timezone.utc), 101)


@pytest.mark.asyncio
async def test_pool_readiness_marker_expires_before_pool_and_rebuild_trigger_is_rate_limited(repository):
    token = current_tenant_id.set(5)
    try:
        assert not await repository.is_pool_version_ready(5, "pool-a")
        await repository.mark_pool_version_ready(5, "pool-a")
        assert await repository.is_pool_version_ready(5, "pool-a")
        assert await repository.acquire_pool_rebuild_trigger(5, ttl_seconds=60)
        assert not await repository.acquire_pool_rebuild_trigger(5, ttl_seconds=60)
    finally:
        current_tenant_id.reset(token)

    redis = repository.redis.async_connection
    assert redis.expirations[repository.pool_ready_key(5, "pool-a")] == 48 * 60 * 60 - 5 * 60
    assert redis.expirations[repository.pool_rebuild_trigger_key(5)] == 60

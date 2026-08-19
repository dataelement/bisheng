import asyncio

import pytest

from bisheng.core.lock.token_safe_redis_lock import (
    RedisLockBusyError,
    RedisLockLostError,
    TokenSafeRedisLock,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.set_calls = []
        self.eval_calls = []
        self.renew_allowed = True

    async def set(self, name, value, *, nx=False, ex=None):
        self.set_calls.append((name, value, nx, ex))
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    async def eval(self, script, numkeys, key, token, *args):
        self.eval_calls.append((script, numkeys, key, token, args))
        if self.values.get(key) != token:
            return 0
        if args:
            if not self.renew_allowed:
                return 0
            return 1
        self.values.pop(key, None)
        return 1


async def test_lock_uses_set_nx_ex():
    redis = FakeRedis()
    lock = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)

    await lock.acquire()

    assert redis.set_calls == [("permission:test", lock.token, True, 10)]
    assert lock.token


async def test_release_compares_token():
    redis = FakeRedis()
    lock = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)
    await lock.acquire()
    redis.values[lock.key] = "new-owner"

    await lock.release()

    assert redis.values[lock.key] == "new-owner"
    assert lock.token in redis.eval_calls[-1]


async def test_same_key_is_mutually_exclusive():
    redis = FakeRedis()
    first = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)
    second = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)
    await first.acquire()

    with pytest.raises(RedisLockBusyError):
        await second.acquire()

    assert first.token != second.token


async def test_bounded_wait_acquires_after_first_owner_releases():
    redis = FakeRedis()
    first = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)
    second = TokenSafeRedisLock(
        redis,
        "permission:test",
        ttl_seconds=10,
        renewal_interval_seconds=3,
        acquire_timeout_seconds=0.1,
        retry_interval_seconds=0.005,
    )
    await first.acquire()

    async def release_first():
        await asyncio.sleep(0.02)
        await first.release()

    release_task = asyncio.create_task(release_first())
    await second.acquire()
    await release_task

    assert redis.values[second.key] == second.token
    assert len(redis.set_calls) > 2
    await second.release()


async def test_bounded_wait_times_out_when_owner_does_not_release():
    redis = FakeRedis()
    first = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)
    second = TokenSafeRedisLock(
        redis,
        "permission:test",
        ttl_seconds=10,
        renewal_interval_seconds=3,
        acquire_timeout_seconds=0.02,
        retry_interval_seconds=0.005,
    )
    await first.acquire()

    with pytest.raises(RedisLockBusyError):
        await second.acquire()

    assert len(redis.set_calls) > 2
    await first.release()


def test_acquire_wait_configuration_is_validated():
    redis = FakeRedis()

    with pytest.raises(ValueError):
        TokenSafeRedisLock(
            redis,
            "permission:test",
            ttl_seconds=10,
            renewal_interval_seconds=3,
            acquire_timeout_seconds=-1,
        )
    with pytest.raises(ValueError):
        TokenSafeRedisLock(
            redis,
            "permission:test",
            ttl_seconds=10,
            renewal_interval_seconds=3,
            acquire_timeout_seconds=1,
            retry_interval_seconds=0,
        )


async def test_renewal_loss_fails_closed():
    redis = FakeRedis()
    lock = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=1, renewal_interval_seconds=0.01)
    await lock.acquire()
    redis.renew_allowed = False
    await asyncio.sleep(0.02)

    with pytest.raises(RedisLockLostError):
        lock.ensure_owned()

    await lock.release()


async def test_context_exit_releases_after_exception():
    redis = FakeRedis()
    lock = TokenSafeRedisLock(redis, "permission:test", ttl_seconds=10, renewal_interval_seconds=3)

    with pytest.raises(ValueError):
        async with lock:
            raise ValueError("boom")

    assert lock.key not in redis.values

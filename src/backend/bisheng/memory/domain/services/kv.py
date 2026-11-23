"""Small key-value port over Redis used by caches, counters and locks.

Kept narrow so services can be tested with ``InMemoryKV`` and do not depend on
the pickle-based helpers of ``RedisClient``. Values are plain strings.
"""

from __future__ import annotations

from typing import Protocol

_RELEASE_SCRIPT = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_RENEW_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)


class MemoryKV(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, *keys: str) -> None: ...

    async def hincrby(self, key: str, field: str, amount: int = 1) -> None: ...

    async def hgetall(self, key: str) -> dict[str, int]: ...

    async def sadd(self, key: str, *members: str) -> None: ...

    async def smembers(self, key: str) -> set[str]: ...

    async def keys(self, pattern: str) -> list[str]: ...

    async def acquire(self, key: str, token: str, ttl_seconds: int) -> bool: ...

    async def renew(self, key: str, token: str, ttl_seconds: int) -> bool: ...

    async def release(self, key: str, token: str) -> bool: ...


def _s(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisKV:
    """MemoryKV over the platform Redis connection (raw commands, no pickle)."""

    def __init__(self, client=None):
        self._client = client

    async def _conn(self):
        if self._client is None:
            from bisheng.core.cache.redis_manager import get_redis_client

            self._client = await get_redis_client()
        return self._client.async_connection

    async def get(self, key):
        return _s(await (await self._conn()).get(key))

    async def set(self, key, value, ttl_seconds=None):
        await (await self._conn()).set(key, value, ex=ttl_seconds)

    async def delete(self, *keys):
        if keys:
            await (await self._conn()).delete(*keys)

    async def hincrby(self, key, field, amount=1):
        await (await self._conn()).hincrby(key, field, amount)

    async def hgetall(self, key):
        raw = await (await self._conn()).hgetall(key)
        return {_s(k): int(_s(v)) for k, v in (raw or {}).items()}

    async def sadd(self, key, *members):
        if members:
            await (await self._conn()).sadd(key, *members)

    async def smembers(self, key):
        return {_s(m) for m in (await (await self._conn()).smembers(key) or set())}

    async def keys(self, pattern):
        return [_s(k) for k in (await (await self._conn()).keys(pattern) or [])]

    async def acquire(self, key, token, ttl_seconds):
        return bool(await (await self._conn()).set(key, token, nx=True, ex=ttl_seconds))

    async def renew(self, key, token, ttl_seconds):
        return bool(await (await self._conn()).eval(_RENEW_SCRIPT, 1, key, token, ttl_seconds * 1000))

    async def release(self, key, token):
        return bool(await (await self._conn()).eval(_RELEASE_SCRIPT, 1, key, token))

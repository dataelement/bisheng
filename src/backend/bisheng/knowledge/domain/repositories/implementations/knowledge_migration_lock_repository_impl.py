from __future__ import annotations

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_lock_repository import (
    KnowledgeMigrationLockRepository,
)

GLOBAL_MIGRATION_LOCK_KEY = "knowledge:file-migration:global-execution-lock"

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class KnowledgeMigrationLockRepositoryImpl(KnowledgeMigrationLockRepository):
    def __init__(
        self,
        *,
        redis_client: RedisClient | None = None,
        key: str = GLOBAL_MIGRATION_LOCK_KEY,
    ):
        self.redis = redis_client
        self.key = key

    async def _redis(self) -> RedisClient:
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    async def acquire(self, token: str, *, ttl_seconds: int) -> bool:
        redis = await self._redis()
        return bool(
            await redis.async_connection.set(
                self.key,
                token,
                nx=True,
                ex=max(1, int(ttl_seconds)),
            )
        )

    async def renew(self, token: str, *, ttl_seconds: int) -> bool:
        redis = await self._redis()
        result = await redis.async_connection.eval(
            _RENEW_SCRIPT,
            1,
            self.key,
            token,
            max(1, int(ttl_seconds)),
        )
        return bool(result)

    async def release(self, token: str) -> bool:
        redis = await self._redis()
        result = await redis.async_connection.eval(
            _RELEASE_SCRIPT,
            1,
            self.key,
            token,
        )
        return bool(result)

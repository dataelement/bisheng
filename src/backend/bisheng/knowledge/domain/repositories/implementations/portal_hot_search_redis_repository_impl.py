"""Redis implementation of the hot-search cache + rebuild lock (F048)."""

from __future__ import annotations

import json
from collections.abc import Sequence

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.tenant_storage import get_redis_key_prefix
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_redis_repository import (
    PortalHotSearchRedisRepository,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalHotSearchItem


class PortalHotSearchRedisRepositoryImpl(PortalHotSearchRedisRepository):
    def __init__(self, *, redis_client: RedisClient | None = None, cache_ttl: int = 691200, lock_ttl: int = 1800):
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self.lock_ttl = lock_ttl

    async def _redis(self) -> RedisClient:
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    @staticmethod
    def _assert_current_tenant(tenant_id: int) -> None:
        current = get_current_tenant_id()
        if current is None or int(current) != int(tenant_id):
            raise PermissionError("hot-search Redis tenant does not match current context")

    @staticmethod
    def _cache_key(tenant_id: int) -> str:
        return f"{get_redis_key_prefix(tenant_id)}portal:hot_search:{tenant_id}"

    @staticmethod
    def _lock_key(tenant_id: int) -> str:
        return f"{get_redis_key_prefix(tenant_id)}portal:hot_search:lock:{tenant_id}"

    async def replace(self, tenant_id: int, items: Sequence[PortalHotSearchItem]) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        payload = json.dumps(
            [{"rank": item.rank, "query": item.query} for item in items],
            ensure_ascii=False,
        )
        await redis.async_connection.set(self._cache_key(tenant_id), payload, ex=self.cache_ttl)

    async def get(self, tenant_id: int) -> list[PortalHotSearchItem] | None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        value = await redis.async_connection.get(self._cache_key(tenant_id))
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode()
        return [PortalHotSearchItem(rank=int(i["rank"]), query=str(i["query"])) for i in json.loads(value)]

    async def acquire_lock(self, tenant_id: int) -> bool:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        return bool(
            await redis.async_connection.set(
                self._lock_key(tenant_id),
                "1",
                nx=True,
                ex=max(int(self.lock_ttl), 1),
            )
        )

    async def release_lock(self, tenant_id: int) -> None:
        self._assert_current_tenant(tenant_id)
        redis = await self._redis()
        await redis.async_connection.delete(self._lock_key(tenant_id))

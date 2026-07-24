from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from bisheng.common.models.config import ConfigDao
from bisheng.core.cache.redis_manager import get_redis_client

RELATION_MODEL_BINDINGS_KEY = "permission_relation_model_bindings_v1"
RELATION_BINDING_LOCK_KEY = "permission:relation_model_bindings:lock"


class PermissionRelationBindingLockError(RuntimeError):
    """关系绑定写锁不可用。"""


class _RedisBindingLock:
    def __init__(self, *, ttl_seconds: int = 10):
        self.ttl_seconds = ttl_seconds
        self.token = secrets.token_hex(16)
        self.redis_client = None

    async def __aenter__(self):
        self.redis_client = await get_redis_client()
        acquired = await self.redis_client.async_connection.set(
            RELATION_BINDING_LOCK_KEY,
            self.token,
            nx=True,
            ex=self.ttl_seconds,
        )
        if not acquired:
            raise PermissionRelationBindingLockError("permission relation binding lock is busy")
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self.redis_client is None:
            return
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
        """
        await self.redis_client.async_connection.eval(
            script,
            1,
            RELATION_BINDING_LOCK_KEY,
            self.token,
        )


class PermissionRelationBindingService:
    """在分布式锁内重读并定向更新共享关系绑定。"""

    def __init__(
        self,
        *,
        load_callback: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None,
        save_callback: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
        lock_factory: Callable[[], AbstractAsyncContextManager] | None = None,
    ):
        self._load_callback = load_callback or self._load_from_config
        self._save_callback = save_callback or self._save_to_config
        self._lock_factory = lock_factory or _RedisBindingLock

    async def get_bindings(self) -> list[dict[str, Any]]:
        return self._normalize(await self._load_callback())

    async def replace_all(self, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = self._normalize(bindings)
        async with self._lock_factory():
            await self._save_callback(normalized)
        return normalized

    async def mutate(
        self,
        mutator: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        async with self._lock_factory():
            current = self._normalize(await self._load_callback())
            updated = self._normalize(mutator([dict(item) for item in current]))
            await self._save_callback(updated)
            return updated

    async def upsert_bindings(self, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        incoming = self._normalize(bindings)

        def _upsert(current: list[dict[str, Any]]) -> list[dict[str, Any]]:
            binding_map = {item["key"]: item for item in current}
            binding_map.update({item["key"]: item for item in incoming})
            return list(binding_map.values())

        return await self.mutate(_upsert)

    async def remove_binding_if_matches(
        self,
        key: str,
        *,
        model_id: str | None,
    ) -> bool:
        removed = False

        def _remove(current: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nonlocal removed
            updated: list[dict[str, Any]] = []
            for binding in current:
                if binding.get("key") != key:
                    updated.append(binding)
                    continue
                if model_id is not None and str(binding.get("model_id")) != str(model_id):
                    updated.append(binding)
                    continue
                removed = True
            return updated

        await self.mutate(_remove)
        return removed

    @staticmethod
    def _normalize(bindings: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        binding_map: dict[str, dict[str, Any]] = {}
        for raw in bindings or []:
            if not isinstance(raw, dict) or not raw.get("key"):
                continue
            binding_map[str(raw["key"])] = dict(raw)
        return [binding_map[key] for key in sorted(binding_map)]

    @staticmethod
    async def _load_from_config() -> list[dict[str, Any]]:
        row = await ConfigDao.aget_config_by_key(RELATION_MODEL_BINDINGS_KEY)
        if row is None or not (row.value or "").strip():
            return []
        try:
            value = json.loads(row.value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    @staticmethod
    async def _save_to_config(bindings: list[dict[str, Any]]) -> None:
        await ConfigDao.insert_or_update_config(
            RELATION_MODEL_BINDINGS_KEY,
            json.dumps(bindings, ensure_ascii=False),
        )

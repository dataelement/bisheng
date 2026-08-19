from __future__ import annotations

import copy
import inspect
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from bisheng.core.lock import TokenSafeRedisLock
from bisheng.permission.domain.services.relation_model_store import get_bindings, save_bindings

RELATION_BINDING_LOCK_KEY = "{permission_relation_model_bindings_v1}:mutation-lock"


class RelationBindingMutation:
    def __init__(self, *, lock, snapshot: list[dict], save: Callable[[list[dict]], Awaitable[None]]):
        self._lock = lock
        self.snapshot = copy.deepcopy(snapshot)
        self.bindings = copy.deepcopy(snapshot)
        self._save = save
        self._commit_attempted = False

    def ensure_owned(self) -> None:
        self._lock.ensure_owned()

    async def commit(self, bindings: list[dict]) -> list[dict]:
        self.ensure_owned()
        normalized = copy.deepcopy(bindings)
        if normalized == self.bindings:
            return copy.deepcopy(self.bindings)
        self._commit_attempted = True
        await self._save(normalized)
        self.ensure_owned()
        self.bindings = normalized
        return copy.deepcopy(self.bindings)

    async def restore(self) -> None:
        self.ensure_owned()
        if self._commit_attempted or self.bindings != self.snapshot:
            await self._save(copy.deepcopy(self.snapshot))
            self.ensure_owned()
            self.bindings = copy.deepcopy(self.snapshot)
            self._commit_attempted = False


class RelationBindingMutationService:
    """Serializes whole-document relation binding read/modify/write operations."""

    def __init__(
        self,
        *,
        get_bindings: Callable[[], Awaitable[list[dict]]] = get_bindings,
        save_bindings: Callable[[list[dict]], Awaitable[None]] = save_bindings,
        lock_factory: Callable[[str], object] | None = None,
    ):
        self._get_bindings = get_bindings
        self._save_bindings = save_bindings
        self._lock_factory = lock_factory or self._default_lock_factory

    @staticmethod
    def _default_lock_factory(key: str) -> TokenSafeRedisLock:
        from bisheng.common.services.config_service import settings
        from bisheng.core.cache.redis_manager import get_redis_client_sync

        config = settings.approval_invite
        return TokenSafeRedisLock(
            get_redis_client_sync(),
            key,
            ttl_seconds=config.binding_lock_ttl_seconds,
            renewal_interval_seconds=config.binding_lock_renewal_interval_seconds,
            acquire_timeout_seconds=config.binding_lock_ttl_seconds,
            retry_interval_seconds=0.1,
        )

    @asynccontextmanager
    async def transaction(self):
        lock = self._lock_factory(RELATION_BINDING_LOCK_KEY)
        async with lock:
            lock.ensure_owned()
            snapshot = await self._get_bindings()
            lock.ensure_owned()
            yield RelationBindingMutation(lock=lock, snapshot=snapshot, save=self._save_bindings)

    async def mutate(self, mutator: Callable[[list[dict]], list[dict] | Awaitable[list[dict]]]) -> list[dict]:
        async with self.transaction() as transaction:
            result = mutator(copy.deepcopy(transaction.bindings))
            if inspect.isawaitable(result):
                result = await result
            return await transaction.commit(result)

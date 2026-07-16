"""Interface for hot-search Redis cache + rebuild lock (F048)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalHotSearchItem


class PortalHotSearchRedisRepository(ABC):
    @abstractmethod
    async def replace(self, tenant_id: int, items: Sequence[PortalHotSearchItem]) -> None:
        """Overwrite the cached snapshot for a tenant."""

    @abstractmethod
    async def get(self, tenant_id: int) -> list[PortalHotSearchItem] | None:
        """Return the cached snapshot, or None on cache miss."""

    @abstractmethod
    async def acquire_lock(self, tenant_id: int) -> bool:
        """Try to acquire the per-tenant rebuild lock (SET NX EX)."""

    @abstractmethod
    async def release_lock(self, tenant_id: int) -> None:
        """Release the per-tenant rebuild lock."""

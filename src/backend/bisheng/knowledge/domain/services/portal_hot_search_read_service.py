"""Home-page read path for portal hot searches (F048)."""

from __future__ import annotations

from loguru import logger

from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_redis_repository import (
    PortalHotSearchRedisRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_hot_search_repository import (
    PortalHotSearchRepository,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalHotSearchItem


class PortalHotSearchReadService:
    """Redis-first read with MySQL fallback + backfill.

    Best-effort: any storage error yields an empty list so the home page is
    never blocked by the hot-search module.
    """

    def __init__(
        self,
        *,
        redis_repository: PortalHotSearchRedisRepository,
        snapshot_repository: PortalHotSearchRepository,
        top_k: int = 5,
    ) -> None:
        self.redis_repository = redis_repository
        self.snapshot_repository = snapshot_repository
        self.top_k = top_k

    async def list_for_home(self, tenant_id: int) -> list[PortalHotSearchItem]:
        try:
            cached = await self.redis_repository.get(tenant_id)
        except Exception:
            logger.warning("hot-search redis read failed tenant={}", tenant_id)
            cached = None
        # Empty list is a negative cache from a zero-result rebuild; fall back to MySQL.
        if cached:
            return cached[: self.top_k]

        try:
            items = await self.snapshot_repository.list_home_snapshot(top_k=self.top_k)
        except Exception:
            logger.warning("hot-search snapshot read failed tenant={}", tenant_id)
            return []

        if items:
            try:
                await self.redis_repository.replace(tenant_id, items)
            except Exception:
                logger.warning("hot-search redis backfill failed tenant={}", tenant_id)
        return items

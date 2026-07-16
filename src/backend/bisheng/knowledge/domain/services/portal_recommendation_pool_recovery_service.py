"""Rate-limited recovery when the online path observes a missing active pool."""

from __future__ import annotations

import logging
from collections.abc import Callable

from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_redis_repository import (
    PortalRecommendationRedisRepository,
)

logger = logging.getLogger(__name__)


class PortalRecommendationPoolRecoveryService:
    @staticmethod
    async def trigger_if_needed(
        repository: PortalRecommendationRedisRepository,
        tenant_id: int,
        *,
        enqueue: Callable[[int], None] | None = None,
    ) -> bool:
        try:
            if not await repository.acquire_pool_rebuild_trigger(tenant_id):
                return False
            if enqueue is None:
                from bisheng.worker.knowledge.portal_recommendation import (
                    enqueue_portal_recommendation_pool_rebuild,
                )

                enqueue_portal_recommendation_pool_rebuild(tenant_id=tenant_id)
            else:
                enqueue(tenant_id)
            return True
        except Exception:
            logger.exception(
                "failed to trigger missing recommendation pool rebuild tenant_id=%s",
                tenant_id,
            )
            return False

"""Per-user short-TTL cache for a user's accessible knowledge-space list.

Caches the exact `_format_accessible_spaces` output (a list of
`KnowledgeSpaceInfoResp`) for `_list_accessible_spaces`, so repeated
grouped/visible-space calls within the TTL window skip the recompute
(permission fan-out, DB joins, etc.) entirely.

Pure TTL, no active invalidation — the grouped/visible-space list tolerates
a few seconds of staleness. Degrades to no-op when Redis is unavailable.
"""
from __future__ import annotations

import logging

from bisheng.core.cache.redis_manager import get_redis_client

logger = logging.getLogger(__name__)

KEY_PREFIX = 'ksp:accessible:'
SPACE_LIST_CACHE_TTL = 15  # seconds


def _tenant_id() -> int:
    from bisheng.core.context.tenant import get_current_tenant_id
    return get_current_tenant_id() or 1


def _key(user_id: int, order_by: str) -> str:
    return f'{KEY_PREFIX}{_tenant_id()}:{user_id}:{order_by}'


class SpaceListCache:
    """Stateless cache helper for a user's accessible-space list. All methods are @classmethod."""

    @classmethod
    async def get(cls, user_id: int, order_by: str):
        """Get the cached accessible-space list for a user. Returns None on miss/unavailable."""
        try:
            redis = await get_redis_client()
            if redis is None:
                return None
            raw = await redis.aget(_key(user_id, order_by))
            if raw is None:
                return None
            from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
                KnowledgeSpaceInfoResp,
            )
            return [KnowledgeSpaceInfoResp.model_validate(item) for item in raw]
        except Exception as e:
            logger.debug('SpaceListCache.get error: %s', e)
            return None

    @classmethod
    async def set(cls, user_id: int, order_by: str, spaces: list) -> None:
        """Cache the accessible-space list for a user with a short TTL."""
        try:
            redis = await get_redis_client()
            if redis is None:
                return
            payload = [s.model_dump(mode='json') for s in spaces]
            await redis.aset(_key(user_id, order_by), payload, expiration=SPACE_LIST_CACHE_TTL)
        except Exception as e:
            logger.debug('SpaceListCache.set error: %s', e)

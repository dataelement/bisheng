"""PermissionCache — L2 Redis cache for permission checks (T08).

Key patterns:
  perm:chk:{user_id}:{relation}:{object_type}:{object_id} → "1" or "0"
  perm:lst:{user_id}:{relation}:{object_type} → pickled list[str]

TTL: 10 seconds (AC-05).
UNCACHEABLE_RELATIONS (can_manage, can_delete) bypass cache entirely.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

KEY_PREFIX = 'perm:'
TTL = 10  # seconds


class PermissionCache:
    """Stateless cache helper for permission data. All methods are @classmethod."""

    @classmethod
    async def get_check(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        object_id: str,
    ) -> Optional[bool]:
        """Get cached check result. Returns None on miss."""
        try:
            redis = await cls._get_redis()
            if redis is None:
                return None
            key = cls._check_key(user_id, relation, object_type, object_id)
            value = await redis.aget(key)
            if value is not None:
                return bool(value)
            return None
        except Exception as e:
            logger.debug('Cache get_check error: %s', e)
            return None

    @classmethod
    async def set_check(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        object_id: str,
        allowed: bool,
    ) -> None:
        """Cache a check result."""
        try:
            redis = await cls._get_redis()
            if redis is None:
                return
            key = cls._check_key(user_id, relation, object_type, object_id)
            await redis.aset(key, 1 if allowed else 0, expiration=TTL)
        except Exception as e:
            logger.debug('Cache set_check error: %s', e)

    @classmethod
    async def get_list_objects(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
    ) -> Optional[List[str]]:
        """Get cached list_objects result. Returns None on miss."""
        try:
            redis = await cls._get_redis()
            if redis is None:
                return None
            key = cls._list_key(user_id, relation, object_type)
            value = await redis.aget(key)
            if value is not None and isinstance(value, list):
                return value
            return None
        except Exception as e:
            logger.debug('Cache get_list_objects error: %s', e)
            return None

    @classmethod
    async def set_list_objects(
        cls,
        user_id: int,
        relation: str,
        object_type: str,
        ids: List[str],
    ) -> None:
        """Cache a list_objects result."""
        try:
            redis = await cls._get_redis()
            if redis is None:
                return
            key = cls._list_key(user_id, relation, object_type)
            await redis.aset(key, ids, expiration=TTL)
        except Exception as e:
            logger.debug('Cache set_list_objects error: %s', e)

    @classmethod
    async def invalidate_user(cls, user_id: int) -> None:
        """Invalidate all permission cache entries for a user.

        Uses SCAN to find keys matching perm:*:{user_id}:* pattern.
        """
        try:
            redis = await cls._get_redis()
            if redis is None:
                return

            # Use raw async connection for SCAN
            conn = redis.async_connection
            pattern = f'{KEY_PREFIX}*:{user_id}:*'
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await conn.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await conn.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            if deleted:
                logger.debug('Invalidated %d cache entries for user %d', deleted, user_id)
        except Exception as e:
            logger.debug('Cache invalidate_user error: %s', e)

    @classmethod
    async def invalidate_all(cls) -> None:
        """Invalidate all permission cache entries."""
        try:
            redis = await cls._get_redis()
            if redis is None:
                return

            conn = redis.async_connection
            pattern = f'{KEY_PREFIX}*'
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await conn.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    await conn.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            if deleted:
                logger.debug('Invalidated %d total permission cache entries', deleted)
        except Exception as e:
            logger.debug('Cache invalidate_all error: %s', e)

    # ── Key builders ────────────────────────────────────────────

    @staticmethod
    def _check_key(user_id: int, relation: str, object_type: str, object_id: str) -> str:
        return f'{KEY_PREFIX}chk:{user_id}:{relation}:{object_type}:{object_id}'

    @staticmethod
    def _list_key(user_id: int, relation: str, object_type: str) -> str:
        return f'{KEY_PREFIX}lst:{user_id}:{relation}:{object_type}'

    @staticmethod
    async def _get_redis():
        """Get RedisClient instance. Returns None if unavailable."""
        try:
            from bisheng.core.cache.redis_manager import get_redis_client
            return await get_redis_client()
        except Exception:
            return None

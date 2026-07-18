"""Department-scoped controls for workstation daily chat.

This module is intentionally small because it sits on the workstation import
path. Keep imports lightweight and avoid depending on workstation services.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

logger = logging.getLogger(__name__)

_SLOT_TTL_SECONDS = 6 * 60 * 60


class DepartmentFlowService:
    """Resolve and enforce department concurrent daily-chat slots."""

    @classmethod
    async def resolve_limit_and_dept(cls, login_user) -> Tuple[int, Optional[int]]:
        """Return ``(limit, department_id)`` for the user's daily-chat scope.

        The user's primary department is the starting point. Limits inherit from
        the nearest ancestor with ``concurrent_session_limit > 0``; ``0`` means
        "no limit configured here".
        """
        try:
            primary = await UserDepartmentDao.aget_user_primary_department(
                int(login_user.user_id),
            )
            if primary is None:
                return 0, None

            dept = await DepartmentDao.aget_by_id(int(primary.department_id))
            seen: set[int] = set()
            while dept is not None and int(dept.id) not in seen:
                seen.add(int(dept.id))
                limit = int(getattr(dept, 'concurrent_session_limit', 0) or 0)
                if limit > 0:
                    return limit, int(dept.id)
                if dept.parent_id is None:
                    break
                dept = await DepartmentDao.aget_by_id(int(dept.parent_id))
        except Exception as exc:
            logger.warning(
                'Failed to resolve department daily-chat limit for user=%s: %s',
                getattr(login_user, 'user_id', None),
                exc,
            )
        return 0, None

    @classmethod
    async def try_acquire_daily_chat_slot(
        cls,
        department_id: int,
        user_id: int,
        limit: int,
    ) -> bool:
        """Acquire a department slot for ``user_id``.

        A user opening multiple streams in the same department counts once, with
        a per-user reference count so each stream can release independently.
        Redis failures fail open because traffic control must not take down chat.
        """
        if limit <= 0:
            return True
        try:
            redis = await get_redis_client()
            counts_key, total_key = cls._slot_keys(department_id)
            user_field = str(int(user_id))
            script = """
local counts_key = KEYS[1]
local total_key = KEYS[2]
local user_field = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local current = tonumber(redis.call('HGET', counts_key, user_field) or '0')
if current > 0 then
  redis.call('HINCRBY', counts_key, user_field, 1)
  redis.call('EXPIRE', counts_key, ttl)
  redis.call('EXPIRE', total_key, ttl)
  return 1
end

local total = tonumber(redis.call('GET', total_key) or '0')
if total >= limit then
  return 0
end

redis.call('HSET', counts_key, user_field, 1)
redis.call('INCR', total_key)
redis.call('EXPIRE', counts_key, ttl)
redis.call('EXPIRE', total_key, ttl)
return 1
"""
            result = await redis.async_connection.eval(
                script,
                2,
                counts_key,
                total_key,
                user_field,
                int(limit),
                _SLOT_TTL_SECONDS,
            )
            return int(result) == 1
        except Exception as exc:
            logger.warning(
                'Failed to acquire department daily-chat slot, dept=%s user=%s: %s',
                department_id,
                user_id,
                exc,
            )
            return True

    @classmethod
    async def release_daily_chat_slot(cls, department_id: int, user_id: int) -> None:
        """Release one previously acquired daily-chat slot reference."""
        try:
            redis = await get_redis_client()
            counts_key, total_key = cls._slot_keys(department_id)
            user_field = str(int(user_id))
            script = """
local counts_key = KEYS[1]
local total_key = KEYS[2]
local user_field = ARGV[1]
local ttl = tonumber(ARGV[2])

local current = tonumber(redis.call('HGET', counts_key, user_field) or '0')
if current <= 0 then
  return 0
end

if current > 1 then
  redis.call('HINCRBY', counts_key, user_field, -1)
else
  redis.call('HDEL', counts_key, user_field)
  local total = tonumber(redis.call('GET', total_key) or '0')
  if total > 0 then
    redis.call('DECR', total_key)
  else
    redis.call('SET', total_key, 0)
  end
end

redis.call('EXPIRE', counts_key, ttl)
redis.call('EXPIRE', total_key, ttl)
return 1
"""
            await redis.async_connection.eval(
                script,
                2,
                counts_key,
                total_key,
                user_field,
                _SLOT_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                'Failed to release department daily-chat slot, dept=%s user=%s: %s',
                department_id,
                user_id,
                exc,
            )

    @staticmethod
    def _slot_keys(department_id: int) -> Tuple[str, str]:
        dept = int(department_id)
        return (
            f'bisheng:daily_chat:dept:{dept}:user_counts',
            f'bisheng:daily_chat:dept:{dept}:total_users',
        )

from __future__ import annotations

from contextlib import asynccontextmanager

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.lock.token_safe_redis_lock import TokenSafeRedisLock


@asynccontextmanager
async def approval_invite_business_lock(key: str):
    """Serialize invite de-duplication without making Redis the fact source."""

    from bisheng.common.services.config_service import settings

    redis = await get_redis_client()
    ttl_seconds = settings.approval_invite.business_lock_ttl_seconds
    lock = TokenSafeRedisLock(
        redis,
        key,
        ttl_seconds=ttl_seconds,
        renewal_interval_seconds=max(0.1, ttl_seconds / 3),
        acquire_timeout_seconds=ttl_seconds,
        retry_interval_seconds=0.05,
    )
    async with lock:
        yield lock

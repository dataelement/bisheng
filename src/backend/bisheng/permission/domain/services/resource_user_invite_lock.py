from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.lock.token_safe_redis_lock import TokenSafeRedisLock


def _require_positive_integer(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_resource_identity(value: str | int, *, field_name: str) -> str:
    normalized = str(value)
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def build_resource_user_invite_business_key(
    *,
    resource_type: str,
    resource_id: str | int,
    target_user_id: int,
) -> str:
    normalized_resource_type = _require_resource_identity(
        resource_type,
        field_name="resource_type",
    )
    normalized_resource_id = _require_resource_identity(
        resource_id,
        field_name="resource_id",
    )
    normalized_target_user_id = _require_positive_integer(
        target_user_id,
        field_name="target_user_id",
    )
    return f"resource-user-invite:{normalized_resource_type}:{normalized_resource_id}:user:{normalized_target_user_id}"


def build_resource_user_invite_lock_key(
    *,
    tenant_id: int,
    resource_type: str,
    resource_id: str | int,
    target_user_id: int,
) -> str:
    normalized_tenant_id = _require_positive_integer(tenant_id, field_name="tenant_id")
    normalized_resource_type = _require_resource_identity(
        resource_type,
        field_name="resource_type",
    )
    normalized_resource_id = _require_resource_identity(
        resource_id,
        field_name="resource_id",
    )
    normalized_target_user_id = _require_positive_integer(
        target_user_id,
        field_name="target_user_id",
    )
    return (
        f"permission:resource-user-invite:{normalized_tenant_id}:"
        f"{normalized_resource_type}:{normalized_resource_id}:{normalized_target_user_id}"
    )


async def _release_preserving_business_error(lock: TokenSafeRedisLock) -> None:
    try:
        await lock.release()
    except Exception:
        # Releasing is best-effort only when a business error already determines the outcome.
        logger.exception(
            "resource user invite lock release failed while preserving business error for key={}",
            lock.key,
        )


@asynccontextmanager
async def resource_user_invite_lock(
    *,
    tenant_id: int,
    resource_type: str,
    resource_id: str | int,
    target_user_id: int,
    redis_client=None,
    ttl_seconds: int | None = None,
) -> AsyncIterator[TokenSafeRedisLock]:
    lock_key = build_resource_user_invite_lock_key(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        target_user_id=target_user_id,
    )
    if ttl_seconds is None:
        from bisheng.common.services.config_service import settings

        ttl_seconds = settings.approval_invite.business_lock_ttl_seconds
    normalized_ttl_seconds = _require_positive_integer(
        ttl_seconds,
        field_name="ttl_seconds",
    )
    if redis_client is None:
        redis_client = await get_redis_client()

    lock = TokenSafeRedisLock(
        redis_client,
        lock_key,
        ttl_seconds=normalized_ttl_seconds,
        renewal_interval_seconds=max(0.1, normalized_ttl_seconds / 3),
        acquire_timeout_seconds=normalized_ttl_seconds,
        retry_interval_seconds=0.05,
    )
    await lock.acquire()
    try:
        yield lock
    except BaseException:
        await _release_preserving_business_error(lock)
        raise
    else:
        try:
            await lock.release()
        except Exception:
            logger.exception("resource user invite lock release failed for key={}", lock.key)
            raise

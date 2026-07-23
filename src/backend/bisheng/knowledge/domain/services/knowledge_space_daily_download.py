"""Shared per-user daily download quota for knowledge-space downloads.

Used by both workbench ``get_file_download`` and portal watermark PDF download.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bisheng.common.errcode.knowledge_space import (
    DailyDownloadLimitExceededError,
    PortalPdfDownloadServiceUnavailableError,
)


class KnowledgeSpaceDailyDownloadCounter:
    """Per-user daily download counter keyed by Asia/Shanghai calendar day."""

    KEY_PREFIX = "bisheng:ks_download:daily"

    def __init__(
        self,
        redis_client: Any | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._redis = getattr(redis_client, "async_connection", redis_client)
        self.now_provider = now_provider or (lambda: datetime.now(ZoneInfo("Asia/Shanghai")))

    async def _connection(self) -> Any:
        if self._redis is None:
            from bisheng.core.cache.redis_manager import get_redis_client

            client = await get_redis_client()
            self._redis = client.async_connection
        return self._redis

    @classmethod
    def _key(cls, tenant_id: int, user_id: int, day: str) -> str:
        return f"{cls.KEY_PREFIX}:{int(tenant_id)}:{int(user_id)}:{day}"

    def _day_and_ttl(self) -> tuple[str, int]:
        now = self.now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        else:
            now = now.astimezone(ZoneInfo("Asia/Shanghai"))
        day = now.strftime("%Y%m%d")
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        # Expire shortly after next Shanghai midnight so stale day keys are cleaned up.
        ttl_seconds = max(int((tomorrow - now).total_seconds()) + 3600, 3600)
        return day, ttl_seconds

    async def get_count(self, *, tenant_id: int, user_id: int) -> int:
        day, _ = self._day_and_ttl()
        try:
            redis = await self._connection()
            raw = await redis.get(self._key(tenant_id, user_id, day))
        except Exception:
            raise PortalPdfDownloadServiceUnavailableError() from None
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def increment(self, *, tenant_id: int, user_id: int) -> int:
        day, ttl_seconds = self._day_and_ttl()
        key = self._key(tenant_id, user_id, day)
        try:
            redis = await self._connection()
            value = await redis.incr(key)
            await redis.expire(key, ttl_seconds)
        except Exception:
            raise PortalPdfDownloadServiceUnavailableError() from None
        return int(value)


async def should_enforce_knowledge_space_daily_download(login_user: Any) -> bool:
    """Super admin and tenant admin are exempt from the daily download cap."""
    if callable(getattr(login_user, "is_admin", None)) and login_user.is_admin():
        return False
    tenant_id = int(getattr(login_user, "tenant_id", 0) or 0)
    has_tenant_admin = getattr(login_user, "has_tenant_admin", None)
    if callable(has_tenant_admin) and tenant_id and await has_tenant_admin(tenant_id):
        return False
    return True


async def resolve_knowledge_space_daily_download_limit(login_user: Any) -> int:
    from bisheng.role.domain.services.quota_service import QuotaService

    return int(await QuotaService.get_knowledge_space_download_daily_limit(login_user))


async def enforce_knowledge_space_daily_download(
    login_user: Any,
    *,
    counter: KnowledgeSpaceDailyDownloadCounter | None = None,
    limit_resolver: Callable[[Any], Any] | None = None,
) -> None:
    """Raise when the user has already reached today's download limit."""
    if not await should_enforce_knowledge_space_daily_download(login_user):
        return
    if limit_resolver is not None:
        limit = int(await limit_resolver(login_user))
    else:
        limit = await resolve_knowledge_space_daily_download_limit(login_user)
    if limit < 0:
        return
    tenant_id = int(getattr(login_user, "tenant_id", 0) or 0)
    user_id = int(getattr(login_user, "user_id", 0) or 0)
    daily_counter = counter or KnowledgeSpaceDailyDownloadCounter()
    used = await daily_counter.get_count(tenant_id=tenant_id, user_id=user_id)
    if used >= limit:
        raise DailyDownloadLimitExceededError()


async def record_knowledge_space_daily_download(
    login_user: Any,
    *,
    counter: KnowledgeSpaceDailyDownloadCounter | None = None,
    limit_resolver: Callable[[Any], Any] | None = None,
) -> None:
    """Increment today's counter after a successful download prepare."""
    if not await should_enforce_knowledge_space_daily_download(login_user):
        return
    if limit_resolver is not None:
        limit = int(await limit_resolver(login_user))
    else:
        limit = await resolve_knowledge_space_daily_download_limit(login_user)
    if limit < 0:
        return
    tenant_id = int(getattr(login_user, "tenant_id", 0) or 0)
    user_id = int(getattr(login_user, "user_id", 0) or 0)
    daily_counter = counter or KnowledgeSpaceDailyDownloadCounter()
    await daily_counter.increment(tenant_id=tenant_id, user_id=user_id)

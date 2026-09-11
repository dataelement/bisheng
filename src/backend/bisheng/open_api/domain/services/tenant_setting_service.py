"""Short-lived cache for tenant personal-token controls."""

from __future__ import annotations

from dataclasses import dataclass

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.open_api.domain.models.open_api_tenant_setting import (
    DEFAULT_PAT_TTL_DAYS,
    OpenApiTenantSetting,
)
from bisheng.open_api.domain.repositories.tenant_setting_repository import TenantSettingRepository
from bisheng.open_api.domain.schemas.personal_token import (
    PersonalTokenSettingResponse,
    PersonalTokenSettingUpdate,
)

TENANT_PAT_CACHE_KEY = "oapi:tenant:{tenant_id}:pat"
TENANT_PAT_CACHE_TTL_SECONDS = 5


@dataclass(frozen=True, slots=True)
class TenantPatPolicy:
    enabled: bool
    ttl_days: int


class TenantSettingService:
    @classmethod
    async def get_policy(cls, tenant_id: int) -> TenantPatPolicy:
        redis = await get_redis_client()
        key = TENANT_PAT_CACHE_KEY.format(tenant_id=tenant_id)
        cached = await redis.aget(key)
        if cached is not None:
            return TenantPatPolicy(
                enabled=bool(cached["enabled"]),
                ttl_days=int(cached["ttl_days"]),
            )

        row = await TenantSettingRepository.get(tenant_id)
        policy = TenantPatPolicy(
            enabled=bool(row.pat_enabled) if row is not None else False,
            ttl_days=int(row.pat_ttl_days) if row is not None else DEFAULT_PAT_TTL_DAYS,
        )
        await redis.aset(
            key,
            {"enabled": policy.enabled, "ttl_days": policy.ttl_days},
            expiration=TENANT_PAT_CACHE_TTL_SECONDS,
        )
        return policy

    @classmethod
    def get_policy_sync(cls, tenant_id: int) -> TenantPatPolicy:
        row = TenantSettingRepository.get_sync(tenant_id)
        return TenantPatPolicy(
            enabled=bool(row.pat_enabled) if row is not None else False,
            ttl_days=int(row.pat_ttl_days) if row is not None else DEFAULT_PAT_TTL_DAYS,
        )

    @classmethod
    async def get_response(cls, tenant_id: int) -> PersonalTokenSettingResponse:
        policy = await cls.get_policy(tenant_id)
        deployment_enabled = bool(settings.open_api.pat_enabled)
        return PersonalTokenSettingResponse(
            deployment_enabled=deployment_enabled,
            pat_enabled=policy.enabled,
            effective_enabled=deployment_enabled and policy.enabled,
            pat_ttl_days=policy.ttl_days,
        )

    @classmethod
    async def update(
        cls,
        tenant_id: int,
        request: PersonalTokenSettingUpdate,
    ) -> PersonalTokenSettingResponse:
        row = await TenantSettingRepository.get(tenant_id)
        if row is None:
            row = OpenApiTenantSetting(tenant_id=tenant_id)
        row.pat_enabled = request.pat_enabled
        row.pat_ttl_days = request.pat_ttl_days
        await TenantSettingRepository.save(row)
        await cls.invalidate(tenant_id)
        return await cls.get_response(tenant_id)

    @staticmethod
    async def invalidate(tenant_id: int) -> None:
        redis = await get_redis_client()
        await redis.adelete(TENANT_PAT_CACHE_KEY.format(tenant_id=tenant_id))


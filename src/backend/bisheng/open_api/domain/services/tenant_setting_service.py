"""Short-lived cache for tenant personal-token controls."""

from __future__ import annotations

from dataclasses import dataclass

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.open_api.domain.models.open_api_tenant_setting import (
    DEFAULT_PAT_TTL_DAYS,
    OpenApiTenantSetting,
)
from bisheng.open_api.domain.repositories.tenant_setting_repository import TenantSettingRepository
from bisheng.open_api.domain.schemas.personal_token import (
    PersonalTokenSettingResponse,
    PersonalTokenSettingUpdate,
)
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL

TENANT_PAT_CACHE_KEY = "oapi:tenant:{tenant_id}:pat"
TENANT_PAT_CACHE_TTL_SECONDS = 5

AUDIT_ACTION_SETTINGS_UPDATE = "open_api.pat.settings.update"
_AUDITED_FIELDS = ("pat_enabled", "pat_ttl_days", "pat_data_scope")


def _scope_from_store(value: object) -> str:
    """Interpret a stored data-scope value, failing closed on unknowns.

    ``None`` only occurs defensively (the column carries a server default);
    any unknown non-null value can only come from a newer writer, so it is
    read as the narrow scope.
    """

    if value is None or value == DATA_SCOPE_ALL:
        return DATA_SCOPE_ALL
    return DATA_SCOPE_PERSONAL


def _scope_from_cache(cached: dict) -> str:
    """Interpret a cached policy dict written by any process version.

    A missing key is NOT an evaluation failure: during a rolling upgrade the
    pre-F066 processes keep refilling the shared cache without the field, and
    their semantics were exactly ``all_visible`` (design decision 4).
    """

    if "data_scope" not in cached:
        return DATA_SCOPE_ALL
    return _scope_from_store(cached["data_scope"])


@dataclass(frozen=True, slots=True)
class TenantPatPolicy:
    enabled: bool
    ttl_days: int
    data_scope: str = DATA_SCOPE_ALL


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
                data_scope=_scope_from_cache(cached),
            )

        row = await TenantSettingRepository.get(tenant_id)
        policy = TenantPatPolicy(
            enabled=bool(row.pat_enabled) if row is not None else False,
            ttl_days=int(row.pat_ttl_days) if row is not None else DEFAULT_PAT_TTL_DAYS,
            data_scope=_scope_from_store(row.pat_data_scope) if row is not None else DATA_SCOPE_ALL,
        )
        await redis.aset(
            key,
            {"enabled": policy.enabled, "ttl_days": policy.ttl_days, "data_scope": policy.data_scope},
            expiration=TENANT_PAT_CACHE_TTL_SECONDS,
        )
        return policy

    @classmethod
    def get_policy_sync(cls, tenant_id: int) -> TenantPatPolicy:
        row = TenantSettingRepository.get_sync(tenant_id)
        return TenantPatPolicy(
            enabled=bool(row.pat_enabled) if row is not None else False,
            ttl_days=int(row.pat_ttl_days) if row is not None else DEFAULT_PAT_TTL_DAYS,
            data_scope=_scope_from_store(row.pat_data_scope) if row is not None else DATA_SCOPE_ALL,
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
            data_scope=policy.data_scope,
        )

    @classmethod
    async def update(
        cls,
        tenant_id: int,
        request: PersonalTokenSettingUpdate,
        operator=None,
    ) -> PersonalTokenSettingResponse:
        row = await TenantSettingRepository.get(tenant_id)
        if row is None:
            row = OpenApiTenantSetting(tenant_id=tenant_id)
        before = {
            "pat_enabled": bool(row.pat_enabled),
            "pat_ttl_days": int(row.pat_ttl_days),
            "pat_data_scope": _scope_from_store(row.pat_data_scope),
        }
        row.pat_enabled = request.pat_enabled
        row.pat_ttl_days = request.pat_ttl_days
        if request.data_scope is not None:
            # Absent means "keep the stored value" — never substitute a default
            # here, or a stale admin console would silently widen the scope.
            row.pat_data_scope = request.data_scope
        after = {
            "pat_enabled": bool(row.pat_enabled),
            "pat_ttl_days": int(row.pat_ttl_days),
            "pat_data_scope": _scope_from_store(row.pat_data_scope),
        }
        await TenantSettingRepository.save(row)
        await cls.invalidate(tenant_id)
        if operator is not None and any(before[field] != after[field] for field in _AUDITED_FIELDS):
            await AuditLogDao.ainsert_v2(
                tenant_id=tenant_id,
                operator_id=operator.user_id,
                operator_tenant_id=tenant_id,
                action=AUDIT_ACTION_SETTINGS_UPDATE,
                target_type="open_api_tenant_setting",
                target_id=str(tenant_id),
                metadata={"before": before, "after": after},
            )
        return await cls.get_response(tenant_id)

    @staticmethod
    async def invalidate(tenant_id: int) -> None:
        redis = await get_redis_client()
        await redis.adelete(TENANT_PAT_CACHE_KEY.format(tenant_id=tenant_id))


from importlib import import_module

from bisheng.open_api.domain.models.open_api_tenant_setting import DEFAULT_PAT_TTL_DAYS
from bisheng.open_api.domain.schemas.personal_token import PersonalTokenSettingUpdate
from bisheng.open_api.domain.services.tenant_setting_service import (
    TENANT_PAT_CACHE_KEY,
    TENANT_PAT_CACHE_TTL_SECONDS,
    TenantSettingService,
)


async def test_tenant_pat_policy_defaults_closed_and_caches_for_five_seconds(open_api_db, fake_redis):
    policy = await TenantSettingService.get_policy(1)

    assert policy.enabled is False
    assert policy.ttl_days == DEFAULT_PAT_TTL_DAYS
    assert TENANT_PAT_CACHE_TTL_SECONDS == 5
    assert set(fake_redis.values) == {TENANT_PAT_CACHE_KEY.format(tenant_id=1)}


async def test_setting_write_invalidates_and_reloads_cache(open_api_db, fake_redis):
    await TenantSettingService.get_policy(1)
    response = await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=45),
    )

    assert response.pat_enabled is True
    assert response.pat_ttl_days == 45
    assert (await TenantSettingService.get_policy(1)).enabled is True
    assert set(fake_redis.values) == {"oapi:tenant:1:pat"}


def test_pat_migration_is_linear_and_ddl_only():
    migration = import_module(
        "bisheng.core.database.alembic.versions.v3_0_0b1_f053_pat_tenant_setting"
    )
    assert migration.revision == "f053_pat_tenant_setting"
    assert migration.down_revision == "f053_delegate_session_subject"

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
    assert policy.ttl_days == DEFAULT_PAT_TTL_DAYS == 365
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
    migration = import_module("bisheng.core.database.alembic.versions.v3_0_0b1_f053_pat_tenant_setting")
    assert migration.revision == "f053_pat_tenant_setting"
    assert migration.down_revision == "f053_delegate_session_subject"


# ── F066 · data scope on the tenant policy (AC-R1, AC-R6, AC-P28) ──


async def test_data_scope_missing_cache_key_reads_as_all_visible(open_api_db, fake_redis):
    """A pre-F066 process refilling the shared cache must not narrow anyone."""

    fake_redis.values["oapi:tenant:1:pat"] = {"enabled": True, "ttl_days": 30}

    policy = await TenantSettingService.get_policy(1)

    assert policy.enabled is True
    assert policy.data_scope == "all_visible"


async def test_data_scope_unknown_stored_value_fails_closed(open_api_db, fake_redis):
    """A future enum value written by a newer node reads as the narrow scope."""

    from bisheng.open_api.domain.repositories.tenant_setting_repository import TenantSettingRepository

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="personal_only"),
    )
    row = await TenantSettingRepository.get(1)
    row.pat_data_scope = "spaces_only"
    await TenantSettingRepository.save(row)
    fake_redis.values.clear()

    policy = await TenantSettingService.get_policy(1)

    assert policy.data_scope == "personal_only"


async def test_update_without_data_scope_preserves_stored_value(open_api_db, fake_redis):
    """Absent field means "keep": a stale admin console must not widen the scope."""

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="personal_only"),
    )

    response = await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=45),
    )

    assert response.data_scope == "personal_only"
    assert response.pat_ttl_days == 45
    assert (await TenantSettingService.get_policy(1)).data_scope == "personal_only"


async def test_settings_change_writes_audit_only_on_change(open_api_db, fake_redis, monkeypatch):
    from types import SimpleNamespace

    import bisheng.open_api.domain.services.tenant_setting_service as svc

    events: list[dict] = []

    async def record(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(svc.AuditLogDao, "ainsert_v2", record)
    operator = SimpleNamespace(user_id=7)

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30),
        operator=operator,
    )
    assert len(events) == 1
    assert events[0]["action"] == "open_api.pat.settings.update"
    assert events[0]["metadata"]["before"]["pat_data_scope"] == "all_visible"
    assert events[0]["metadata"]["after"]["pat_enabled"] is True

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30),
        operator=operator,
    )
    assert len(events) == 1  # unchanged save leaves no trail

    await TenantSettingService.update(
        1,
        PersonalTokenSettingUpdate(pat_enabled=True, pat_ttl_days=30, data_scope="personal_only"),
        operator=operator,
    )
    assert len(events) == 2
    assert events[1]["metadata"]["after"]["pat_data_scope"] == "personal_only"

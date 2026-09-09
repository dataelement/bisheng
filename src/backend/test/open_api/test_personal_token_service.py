from datetime import datetime
from types import SimpleNamespace

from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models.api_credential import REVOKE_REASON_REGENERATED
from bisheng.open_api.domain.models.open_api_tenant_setting import OpenApiTenantSetting
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.services.credential_service import hash_token
from bisheng.open_api.domain.services.personal_token_service import PersonalTokenService
from bisheng.user.domain.models.user import User


async def _seed(open_api_db):
    async with open_api_db() as session:
        user = User(user_name="holder", password="unused", delete=0)
        session.add(user)
        await session.flush()
        session.add(UserTenant(user_id=user.user_id, tenant_id=1, status="active", is_active=1))
        session.add(OpenApiTenantSetting(tenant_id=1, pat_enabled=True, pat_ttl_days=30))
        await session.commit()
        return user


async def test_issue_is_one_time_plaintext_and_regeneration_revokes_old(
    open_api_db,
    fake_redis,
    monkeypatch,
):
    holder = await _seed(open_api_db)
    events = []

    async def not_admin(_user_id, _tenant_id):
        return False

    async def audit(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(PersonalTokenService, "_is_admin", not_admin)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.personal_token_service.AuditLogDao.ainsert_v2",
        audit,
    )
    operator = SimpleNamespace(user_id=holder.user_id, tenant_id=1)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.tenant_setting_service.settings.open_api.pat_enabled",
        True,
    )

    first = await PersonalTokenService.issue(tenant_id=1, user_id=holder.user_id, operator=operator)
    second = await PersonalTokenService.issue(tenant_id=1, user_id=holder.user_id, operator=operator)
    rows = await CredentialRepository.list_by_subject("natural_person", holder.user_id)

    assert first.plaintext.startswith("bs-pat-")
    assert second.plaintext != first.plaintext
    assert rows[1].revoke_reason == REVOKE_REASON_REGENERATED
    assert rows[0].revoked_at is None
    assert all(first.plaintext not in repr(event) and second.plaintext not in repr(event) for event in events)


async def test_admin_holder_ttl_is_capped_and_flagged(open_api_db, fake_redis, monkeypatch):
    holder = await _seed(open_api_db)

    async def is_admin(_user_id, _tenant_id):
        return True

    async def audit(**_kwargs):
        return None

    monkeypatch.setattr(PersonalTokenService, "_is_admin", is_admin)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.personal_token_service.AuditLogDao.ainsert_v2",
        audit,
    )
    operator = SimpleNamespace(user_id=holder.user_id, tenant_id=1)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.tenant_setting_service.settings.open_api.pat_enabled",
        True,
    )
    before = datetime.now()
    issued = await PersonalTokenService.issue(tenant_id=1, user_id=holder.user_id, operator=operator)

    assert issued.holder_is_admin is True
    assert 6 <= (issued.expires_at - before).days <= 7


async def test_tenant_migration_preserves_pat_and_invalidates_cached_principal(
    open_api_db,
    fake_redis,
    monkeypatch,
):
    holder = await _seed(open_api_db)
    events = []

    async def not_admin(_user_id, _tenant_id):
        return False

    async def audit(**kwargs):
        events.append(kwargs)

    monkeypatch.setattr(PersonalTokenService, "_is_admin", not_admin)
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.personal_token_service.AuditLogDao.ainsert_v2",
        audit,
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.tenant_setting_service.settings.open_api.pat_enabled",
        True,
    )
    operator = SimpleNamespace(user_id=holder.user_id, tenant_id=1)
    issued = await PersonalTokenService.issue(tenant_id=1, user_id=holder.user_id, operator=operator)
    digest = hash_token(issued.plaintext)
    fake_redis.values[f"oapi:cred:{digest}"] = {"stale": True}

    assert await PersonalTokenService.migrate_tenant(user_id=holder.user_id, tenant_id=2) == 1

    row = await CredentialRepository.get_by_hash(digest)
    assert row is not None
    assert row.tenant_id == 2
    assert row.revoked_at is None
    assert f"oapi:cred:{digest}" not in fake_redis.values
    migration = next(event for event in events if event["action"] == "open_api.pat.tenant_migrate")
    assert migration["metadata"]["old_tenant_id"] == 1
    assert migration["metadata"]["new_tenant_id"] == 2

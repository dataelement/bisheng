from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import ServiceAccountNotFoundError, ServiceAccountOwnerInvalidError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_SERVICE_ACCOUNT, ApiCredential
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.schemas.service_account import ServiceAccountCreate, ServiceAccountUpdate
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.user.domain.models.user import User


async def seed_user(open_api_db, user_id: int, tenant_id: int, *, deleted: bool = False):
    async with open_api_db() as session:
        session.add(User(user_id=user_id, user_name=f"user-{user_id}", password="x", delete=int(deleted)))
        session.add(UserTenant(user_id=user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.commit()


def actor(user_id=2, tenant_id=1, *, is_global_super=False):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_global_super=is_global_super)


async def test_create_only_inserts_independent_service_account(open_api_db, fake_redis, audit_events):
    await seed_user(open_api_db, 10, 1)
    async with open_api_db() as session:
        user_count_before = len((await session.exec(select(User))).all())
        membership_count_before = len((await session.exec(select(UserTenant))).all())

    row = await ServiceAccountService.create(
        actor(),
        ServiceAccountCreate(name="integration", description="sync", resource_owner_user_id=10),
    )
    assert row.id is not None and row.resource_owner_user_id == 10

    async with open_api_db() as session:
        assert len((await session.exec(select(ServiceAccount))).all()) == 1
        assert len((await session.exec(select(User))).all()) == user_count_before
        assert len((await session.exec(select(UserTenant))).all()) == membership_count_before
    assert audit_events[-1]["action"] == "open_api.service_account.create"


async def test_owner_must_be_active_and_in_same_tenant(open_api_db, fake_redis, audit_events):
    await seed_user(open_api_db, 10, 2)
    with pytest.raises(ServiceAccountOwnerInvalidError):
        await ServiceAccountService.create(
            actor(tenant_id=1),
            ServiceAccountCreate(name="wrong-tenant", resource_owner_user_id=10),
        )


async def test_global_super_without_scope_derives_tenant_from_owner(open_api_db, fake_redis, audit_events):
    await seed_user(open_api_db, 10, 2)
    token = current_tenant_id.set(None)
    try:
        row = await ServiceAccountService.create(
            actor(tenant_id=1, is_global_super=True),
            ServiceAccountCreate(name="child-integration", resource_owner_user_id=10),
        )
    finally:
        current_tenant_id.reset(token)
    assert row.tenant_id == 2


async def test_update_disable_enable_delete_and_key_invalidation(open_api_db, fake_redis, audit_events):
    await seed_user(open_api_db, 10, 1)
    row = await ServiceAccountService.create(
        actor(),
        ServiceAccountCreate(name="integration", resource_owner_user_id=10),
    )
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=row.id,
        request=KeyIssueRequest(name="key"),
        created_by=2,
    )
    updated = await ServiceAccountService.update(
        actor(), row.id, ServiceAccountUpdate(name="renamed", description="updated")
    )
    assert (updated.name, updated.description) == ("renamed", "updated")

    disabled = await ServiceAccountService.disable(actor(), row.id)
    assert disabled.disabled_at is not None and not disabled.is_enabled
    enabled = await ServiceAccountService.enable(actor(), row.id)
    assert enabled.disabled_at is None and enabled.is_enabled
    deleted = await ServiceAccountService.delete(actor(), row.id)
    assert deleted.deleted_at is not None

    async with open_api_db() as session:
        key = (await session.exec(select(ApiCredential).where(ApiCredential.id == issued.id))).one()
    assert key.revoked_at is not None and key.revoke_reason == "subject_deleted"
    with pytest.raises(ServiceAccountNotFoundError):
        await ServiceAccountService.get_row(row.id)
    assert [event["action"] for event in audit_events] == [
        "open_api.service_account.create",
        "open_api.service_account.update",
        "open_api.service_account.disable",
        "open_api.service_account.enable",
        "open_api.service_account.delete",
    ]


async def test_disabled_owner_is_rejected(open_api_db, fake_redis, audit_events):
    await seed_user(open_api_db, 10, 1, deleted=True)
    with pytest.raises(ServiceAccountOwnerInvalidError):
        await ServiceAccountService.create(
            actor(),
            ServiceAccountCreate(name="invalid-owner", resource_owner_user_id=10),
        )

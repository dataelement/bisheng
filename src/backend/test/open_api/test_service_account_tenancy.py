"""F113: live ownership is checked after every credential-cache lookup."""

from dataclasses import replace
from datetime import datetime

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    ServiceAccountOwnerTenantMismatchError,
    ServiceAccountOwnerTenantUnresolvedError,
)
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.application.service_account_tenancy import (
    require_owner_tenant,
    revalidate_service_account,
)
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.models.service_account import ServiceAccount
from bisheng.open_api.domain.repositories.owner_repository import OwnerRepository
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.user.domain.models.user import User


async def seed(factory, *, owner=21, tenant=1, deleted=0, membership=True):
    async with factory() as session:
        session.add(User(user_id=owner, user_name=f"owner-{owner}", password="", delete=deleted))
        if membership:
            session.add(UserTenant(user_id=owner, tenant_id=tenant, is_active=1, status="active"))
        account = ServiceAccount(tenant_id=1, name=f"f113-{owner}", resource_owner_user_id=owner)
        session.add(account)
        await session.commit()
        await session.refresh(account)
    return account


def principal(account):
    return OpenApiPrincipal(
        credential_id=10,
        actor_kind="service_account",
        actor_id=account.id,
        actor_name=account.name,
        tenant_id=1,
        resource_owner_user_id=account.resource_owner_user_id,
        scopes=frozenset({"knowledge:read"}),
        authorization_subject_type="service_account",
        authorization_subject_id=account.id,
        effective_user_id=None,
    )


async def test_hot_cache_refuses_moved_owner_and_recovers_without_revoking(open_api_db, fake_redis):
    account = await seed(open_api_db)
    key = await CredentialService.issue(
        tenant_id=1,
        subject_kind="service_account",
        subject_id=account.id,
        request=KeyIssueRequest(name="f113", scopes=["knowledge:read"]),
        created_by=3,
    )
    header = f"Bearer {key.plaintext}"
    first = await validate_bearer(header)
    for tenant in (2, 1):
        async with open_api_db() as session:
            member = (await session.exec(select(UserTenant).where(UserTenant.user_id == 21))).one()
            member.tenant_id = tenant
            session.add(member)
            await session.commit()
        if tenant == 2:
            with pytest.raises(ServiceAccountOwnerTenantMismatchError):
                await validate_bearer(header)
        else:
            assert await validate_bearer(header) == first


async def test_rebinding_refreshes_owner_without_inheriting_owner_permissions(open_api_db):
    account = await seed(open_api_db)
    cached = principal(account)
    async with open_api_db() as session:
        session.add(User(user_id=22, user_name="new-owner", password=""))
        session.add(UserTenant(user_id=22, tenant_id=1, is_active=1))
        row = await session.get(ServiceAccount, account.id)
        row.resource_owner_user_id = 22
        row.name = "renamed-account"
        session.add(row)
        await session.commit()
    actual = await revalidate_service_account(cached)
    assert actual.resource_owner_user_id == 22
    assert actual.actor_name == "renamed-account"
    assert actual.authorization_subject_type == "service_account"
    assert actual.authorization_subject_id == cached.authorization_subject_id
    assert actual.scopes == cached.scopes and actual.effective_user_id is None
    assert cached.resource_owner_user_id == 21


async def test_deleted_marker_does_not_add_a_tenant_gate(open_api_db):
    account = await seed(open_api_db, deleted=1)
    assert await revalidate_service_account(principal(account)) == principal(account)
    await require_owner_tenant(21, 1)


@pytest.mark.parametrize("membership", [True, False])
async def test_missing_current_membership_is_not_a_tenant_mismatch(open_api_db, membership):
    account = await seed(open_api_db, membership=membership)
    if membership:
        async with open_api_db() as session:
            row = (await session.exec(select(UserTenant))).one()
            row.status = "disabled"
            session.add(row)
            await session.commit()
    with pytest.raises(ServiceAccountOwnerTenantUnresolvedError):
        await revalidate_service_account(principal(account))
    with pytest.raises(ServiceAccountOwnerTenantUnresolvedError):
        await require_owner_tenant(21, 1)


async def test_ambiguous_relation_fails_closed_instead_of_picking_first(open_api_db, monkeypatch):
    account = await seed(open_api_db)
    binding = await OwnerRepository.get_service_account_execution_binding(account.id)

    async def ambiguous(_id):
        return replace(binding, owner_tenant_ids=(1, 2))

    monkeypatch.setattr(OwnerRepository, "get_service_account_execution_binding", ambiguous)
    with pytest.raises(ServiceAccountOwnerTenantUnresolvedError):
        await revalidate_service_account(principal(account))


async def test_dependency_fault_keeps_its_cause(open_api_db, monkeypatch):
    account = await seed(open_api_db)

    async def failed(_id):
        raise OSError("F113 relationship query unavailable")

    monkeypatch.setattr(OwnerRepository, "get_service_account_execution_binding", failed)
    with pytest.raises(OpenApiAuthDependencyUnavailableError) as error:
        await revalidate_service_account(principal(account))
    assert isinstance(error.value.__cause__, OSError)


async def test_other_principals_do_not_use_the_service_account_gate(monkeypatch):
    async def forbidden(_id):
        pytest.fail("Non-service-account credential queried an owner binding")

    monkeypatch.setattr(OwnerRepository, "get_service_account_execution_binding", forbidden)
    base = principal(ServiceAccount(id=5, tenant_id=1, name="unused", resource_owner_user_id=21))
    for kind in ("natural_person", "hosted_app"):
        other = base.model_copy(update={"actor_kind": kind})
        assert await revalidate_service_account(other) is other


async def test_account_disabled_after_cache_hit_still_refuses(open_api_db):
    from bisheng.common.errcode.open_api import ServiceAccountInactiveError

    account = await seed(open_api_db)
    cached = principal(account)
    async with open_api_db() as session:
        row = await session.get(ServiceAccount, account.id)
        row.disabled_at = datetime.now()
        session.add(row)
        await session.commit()
    with pytest.raises(ServiceAccountInactiveError):
        await revalidate_service_account(cached)

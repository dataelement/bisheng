"""``ServiceAccountService`` unit tests (F049 T013, pairs with T014).

Test-First: written before
``open_api/domain/services/service_account_service.py``. The D1 create unit
(user row + companion row + active ``user_tenant`` row in one transaction) is
the piece with the most ways to be subtly wrong, so it is asserted from both
ends: the happy path and a mid-flight failure.

覆盖 AC: AC-12 (account audit family), AC-19 (single transaction / immediately
grantable), AC-21 (disable and delete kill the keys), AC-23 (owner must be an
enabled natural person of this tenant; tenant comes from the admin context),
AC-27 (changing the owner is not retroactive), AC-28 (a disabled owner does not
cascade), AC-47 (disable / enable keep configuration), AC-48 (delete shape).
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import (
    ServiceAccountNotFoundError,
    ServiceAccountOwnerInvalidError,
)
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.tenant import UserTenant, UserTenantDao
from bisheng.open_api.domain.models.api_credential import (
    REVOKE_REASON_SUBJECT_DELETED,
    SUBJECT_KIND_SERVICE_ACCOUNT,
)
from bisheng.open_api.domain.models.service_account import (
    SERVICE_ACCOUNT_USER_SOURCE,
    ServiceAccount,
    ServiceAccountDao,
)
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.schemas.service_account import ServiceAccountCreate, ServiceAccountUpdate
from bisheng.open_api.domain.services.credential_service import CREDENTIAL_CACHE_KEY, CredentialService
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.user.domain.models.user import USER_TYPE_HUMAN, USER_TYPE_SERVICE, User
from test.open_api.conftest import ROOT_TENANT_ID, SEED_PASSWORD_PLACEHOLDER


async def _user(oapi_db, user_id: int) -> User | None:
    async with oapi_db() as session:
        return (await session.exec(select(User).where(User.user_id == user_id))).first()


async def _companion(oapi_db, user_id: int) -> ServiceAccount | None:
    async with oapi_db() as session:
        return (await session.exec(select(ServiceAccount).where(ServiceAccount.user_id == user_id))).first()


async def _audit_actions(oapi_db) -> list[str]:
    async with oapi_db() as session:
        return [row.action for row in (await session.exec(select(AuditLog))).all()]


async def _seed_user(oapi_db, *, user_id: int, name: str, tenant_id: int, user_type: str, delete: int = 0):
    async with oapi_db() as session:
        session.add(
            User(
                user_id=user_id,
                user_name=name,
                password=SEED_PASSWORD_PLACEHOLDER,
                user_type=user_type,
                delete=delete,
            )
        )
        await session.flush()
        session.add(UserTenant(user_id=user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.commit()


# ---------------------------------------------------------------------------
# create (D1)
# ---------------------------------------------------------------------------


async def test_create_single_transaction(oapi_db, human_user, tenant_admin_payload, monkeypatch):
    """AC-19: three rows land together, in the shape the login guards and pickers rely on."""
    set_current_tenant_id(ROOT_TENANT_ID)
    account = await ServiceAccountService.create(
        tenant_admin_payload,
        ServiceAccountCreate(name="ci-bot", description="nightly", resource_owner_user_id=human_user.user_id),
    )

    principal = await _user(oapi_db, account.user_id)
    assert principal.user_type == USER_TYPE_SERVICE
    assert principal.user_name == "ci-bot"
    assert principal.source == SERVICE_ACCOUNT_USER_SOURCE
    assert principal.external_id is None  # pit 5: the implicit defence for three login paths
    assert principal.password and principal.password != ""
    assert principal.delete == 0

    assert account.tenant_id == ROOT_TENANT_ID
    assert account.resource_owner_user_id == human_user.user_id
    assert account.created_by == tenant_admin_payload.user_id
    assert account.is_enabled

    async with oapi_db() as session:
        tenants = (await session.exec(select(UserTenant).where(UserTenant.user_id == account.user_id))).all()
    assert [(row.tenant_id, row.status, row.is_active) for row in tenants] == [(ROOT_TENANT_ID, "active", 1)]

    # A failure anywhere in the unit leaves no orphan in any of the three tables.
    original = ServiceAccountDao.acreate_with_user

    async def _explode(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("boom after the rows were staged")

    monkeypatch.setattr(ServiceAccountDao, "acreate_with_user", _explode)
    with pytest.raises(RuntimeError):
        await ServiceAccountService.create(
            tenant_admin_payload,
            ServiceAccountCreate(name="doomed", resource_owner_user_id=human_user.user_id),
        )
    async with oapi_db() as session:
        assert (await session.exec(select(User).where(User.user_name == "doomed"))).first() is None
        accounts = (await session.exec(select(ServiceAccount))).all()
        assert [row.user_id for row in accounts] == [account.user_id]
        tenant_rows = (await session.exec(select(UserTenant))).all()
    assert all(row.user_id in {account.user_id, human_user.user_id} for row in tenant_rows)


async def test_create_requires_owner_human_active_same_tenant(oapi_db, human_user, sub_tenant, tenant_admin_payload):
    """AC-23: the resource owner must be an enabled natural person of the acting tenant (26021)."""
    set_current_tenant_id(ROOT_TENANT_ID)

    async def _expect_rejected(owner_id: int):
        with pytest.raises(ServiceAccountOwnerInvalidError) as excinfo:
            await ServiceAccountService.create(
                tenant_admin_payload,
                ServiceAccountCreate(name="rejected", resource_owner_user_id=owner_id),
            )
        assert excinfo.value.code == 26021

    await _expect_rejected(999_999)  # no such user
    await _expect_rejected(sub_tenant.admin_user_id)  # natural person of another tenant

    await _seed_user(
        oapi_db, user_id=90020, name="disabled-owner", tenant_id=ROOT_TENANT_ID, user_type=USER_TYPE_HUMAN, delete=1
    )
    await _expect_rejected(90020)  # disabled natural person

    existing = await ServiceAccountService.create(
        tenant_admin_payload,
        ServiceAccountCreate(name="owner-source", resource_owner_user_id=human_user.user_id),
    )
    await _expect_rejected(existing.user_id)  # a service account can never own resources

    # ``update`` runs the very same predicate.
    with pytest.raises(ServiceAccountOwnerInvalidError):
        await ServiceAccountService.update(
            tenant_admin_payload, existing.user_id, ServiceAccountUpdate(resource_owner_user_id=90020)
        )


async def test_tenant_taken_from_admin_context_not_from_body(oapi_db, sub_tenant, tenant_admin_payload):
    """AC-23 / pit 23: the tenant is the admin's current scope; the request body has no say."""
    set_current_tenant_id(sub_tenant.tenant_id)
    payload = ServiceAccountCreate.model_validate(
        {
            "name": "scoped-bot",
            "resource_owner_user_id": sub_tenant.admin_user_id,
            "tenant_id": ROOT_TENANT_ID,  # ignored: not a field of the schema
        }
    )
    assert not hasattr(payload, "tenant_id")

    account = await ServiceAccountService.create(tenant_admin_payload, payload)
    # The operator's own leaf is Root; the admin-scope view (current tenant) wins.
    assert tenant_admin_payload.tenant_id == ROOT_TENANT_ID
    assert account.tenant_id == sub_tenant.tenant_id
    async with oapi_db() as session:
        row = (await session.exec(select(UserTenant).where(UserTenant.user_id == account.user_id))).first()
    assert row.tenant_id == sub_tenant.tenant_id


async def test_created_account_is_grantable_immediately(oapi_db, service_account_factory):
    """AC-19 / pit 8: F048 subject validation needs ``status='active' AND is_active=1`` — both must be there."""
    account = await service_account_factory("grantable")
    active = await UserTenantDao.aget_active_user_tenant(account.user_id)
    assert active is not None
    assert active.is_active == 1 and active.status == "active"
    assert active.tenant_id == account.tenant_id


# ---------------------------------------------------------------------------
# disable / enable / delete
# ---------------------------------------------------------------------------


async def test_disable_invalidates_keys_within_5s(oapi_db, redis_client, service_account_factory, tenant_admin_payload):
    """AC-21 / AC-47: disabling drops every cached credential but leaves the key rows untouched."""
    account = await service_account_factory("to-disable")
    issued = await CredentialService.issue(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id), KeyIssueRequest(name="k")
    )
    async with oapi_db() as session:
        from bisheng.open_api.domain.models.api_credential import ApiCredentialDao

        token_hash = (await ApiCredentialDao.aget(session, issued.id)).token_hash
    cache_key = CREDENTIAL_CACHE_KEY.format(token_hash)
    await redis_client.aset(cache_key, {"credential_id": issued.id}, expiration=300)

    disabled = await ServiceAccountService.disable(tenant_admin_payload, account.user_id)
    assert disabled.disabled_at is not None and disabled.deleted_at is None
    assert await redis_client.aget(cache_key) is None
    # The rejection itself (26027) is asserted by the validator suite (T011);
    # here the contract is "cache cleared + companion flag set + rows intact".
    keys = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id))
    assert [key.revoked_at for key in keys] == [None]
    assert [key.revoke_reason for key in keys] == [None]
    # Write-through projection so people-facing ``delete == 0`` filters hide it.
    assert (await _user(oapi_db, account.user_id)).delete == 1


async def test_enable_restores(oapi_db, redis_client, service_account_factory, tenant_admin_payload):
    """AC-47: re-enabling restores the account as it was — no key rotation, no config loss."""
    account = await service_account_factory("to-toggle")
    await CredentialService.issue(
        tenant_admin_payload,
        SUBJECT_KIND_SERVICE_ACCOUNT,
        str(account.user_id),
        KeyIssueRequest(name="k", scopes=["knowledge:read"]),
    )
    before = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id))

    await ServiceAccountService.disable(tenant_admin_payload, account.user_id)
    enabled = await ServiceAccountService.enable(tenant_admin_payload, account.user_id)

    assert enabled.disabled_at is None and enabled.deleted_at is None and enabled.is_enabled
    assert enabled.resource_owner_user_id == account.resource_owner_user_id
    assert (await _user(oapi_db, account.user_id)).delete == 0
    after = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id))
    assert [(k.id, k.scopes, k.revoked_at) for k in after] == [(k.id, k.scopes, k.revoked_at) for k in before]


async def test_delete_wave1_shape(oapi_db, redis_client, service_account_factory, tenant_admin_payload):
    """AC-21 / AC-48: delete revokes every key, books the reason and hides the principal."""
    account = await service_account_factory("to-delete")
    await CredentialService.issue(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id), KeyIssueRequest(name="k")
    )

    await ServiceAccountService.delete(tenant_admin_payload, account.user_id)

    companion = await _companion(oapi_db, account.user_id)
    assert companion is not None and companion.deleted_at is not None  # row kept for audit
    assert (await _user(oapi_db, account.user_id)).delete == 1
    keys = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id))
    assert all(key.revoked_at is not None for key in keys)
    assert {key.revoke_reason for key in keys} == {REVOKE_REASON_SUBJECT_DELETED}

    # A deleted account is gone for every management read (26020).
    with pytest.raises(ServiceAccountNotFoundError) as excinfo:
        await ServiceAccountService.get_row(account.user_id)
    assert excinfo.value.code == 26020


# ---------------------------------------------------------------------------
# resource owner
# ---------------------------------------------------------------------------


async def test_change_owner_not_retroactive(oapi_db, human_user, service_account_factory, tenant_admin_payload):
    """AC-27: changing the owner rewrites one companion column and nothing else."""
    account = await service_account_factory("owner-swap")
    await _seed_user(oapi_db, user_id=90030, name="new-owner", tenant_id=ROOT_TENANT_ID, user_type=USER_TYPE_HUMAN)

    updated = await ServiceAccountService.update(
        tenant_admin_payload, account.user_id, ServiceAccountUpdate(resource_owner_user_id=90030)
    )
    assert updated.resource_owner_user_id == 90030
    assert updated.created_by == account.created_by and updated.create_time == account.create_time
    # The service must not reach into business tables to re-home past resources:
    # the fixture database has no ``knowledge`` table at all, so any such write
    # would have raised OperationalError before this line.
    assert (await _companion(oapi_db, account.user_id)).resource_owner_user_id == 90030

    renamed = await ServiceAccountService.update(
        tenant_admin_payload, account.user_id, ServiceAccountUpdate(name="renamed", description="d2")
    )
    assert renamed.resource_owner_user_id == 90030 and renamed.description == "d2"
    assert (await _user(oapi_db, account.user_id)).user_name == "renamed"


async def test_owner_disabled_does_not_cascade(oapi_db, human_user, service_account_factory, tenant_admin_payload):
    """AC-28: a disabled owner flags the row in the list; it never disables the account or its keys."""
    account = await service_account_factory("owner-disabled")
    await CredentialService.issue(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id), KeyIssueRequest(name="k")
    )

    async with oapi_db() as session:
        owner = (await session.exec(select(User).where(User.user_id == human_user.user_id))).first()
        owner.delete = 1
        session.add(owner)
        await session.commit()

    still = await ServiceAccountService.get_row(account.user_id)
    assert still.is_enabled
    keys = await CredentialService.list_by_subject(SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id))
    assert all(key.is_valid for key in keys)

    detail = await ServiceAccountService.get_detail(tenant_admin_payload, account.user_id)
    assert detail.owner_disabled is True
    assert detail.resource_owner.user_id == human_user.user_id and detail.resource_owner.disabled is True
    assert detail.status == "enabled" and detail.active_key_count == 1


# ---------------------------------------------------------------------------
# list + audit
# ---------------------------------------------------------------------------


async def test_list_page_hydrates_columns(
    oapi_db, redis_client, human_user, service_account_factory, tenant_admin_payload
):
    """AC-42 columns come from the service, not the endpoint: names, key counts, owner, idle threshold."""
    set_current_tenant_id(ROOT_TENANT_ID)
    first = await service_account_factory("bot-a")
    await service_account_factory("bot-b")
    await CredentialService.issue(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(first.user_id), KeyIssueRequest(name="k")
    )

    page = await ServiceAccountService.list_page(tenant_admin_payload)
    assert page.total == 2 and page.idle_days == 90
    by_name = {item.name: item for item in page.data}
    assert set(by_name) == {"bot-a", "bot-b"}
    assert by_name["bot-a"].active_key_count == 1 and by_name["bot-b"].active_key_count == 0
    assert by_name["bot-a"].resource_owner.user_id == human_user.user_id
    assert by_name["bot-a"].resource_owner.user_name == human_user.user_name
    assert by_name["bot-a"].status == "enabled" and by_name["bot-a"].owner_disabled is False
    assert by_name["bot-a"].id == first.user_id

    filtered = await ServiceAccountService.list_page(tenant_admin_payload, keyword="bot-b")
    assert [item.name for item in filtered.data] == ["bot-b"]

    await ServiceAccountService.delete(tenant_admin_payload, first.user_id)
    after = await ServiceAccountService.list_page(tenant_admin_payload)
    assert [item.name for item in after.data] == ["bot-b"]  # deleted rows leave the list


async def test_audit_account_family_events(oapi_db, redis_client, human_user, tenant_admin_payload):
    """AC-12: five account events plus the key-invalidation event that disable / delete trigger."""
    set_current_tenant_id(ROOT_TENANT_ID)
    account = await ServiceAccountService.create(
        tenant_admin_payload,
        ServiceAccountCreate(name="audited-bot", resource_owner_user_id=human_user.user_id),
    )
    await CredentialService.issue(
        tenant_admin_payload, SUBJECT_KIND_SERVICE_ACCOUNT, str(account.user_id), KeyIssueRequest(name="k")
    )
    await ServiceAccountService.update(tenant_admin_payload, account.user_id, ServiceAccountUpdate(description="d"))
    await ServiceAccountService.disable(tenant_admin_payload, account.user_id)
    await ServiceAccountService.enable(tenant_admin_payload, account.user_id)
    await ServiceAccountService.delete(tenant_admin_payload, account.user_id)

    actions = await _audit_actions(oapi_db)
    assert {
        "open_api.service_account.create",
        "open_api.service_account.update",
        "open_api.service_account.disable",
        "open_api.service_account.enable",
        "open_api.service_account.delete",
        "open_api.api_key.invalidate_by_subject",
    } <= set(actions)

    async with oapi_db() as session:
        rows = (await session.exec(select(AuditLog))).all()
    invalidations = [row for row in rows if row.action == "open_api.api_key.invalidate_by_subject"]
    assert {row.audit_metadata["reason"] for row in invalidations} == {"subject_disabled", "subject_deleted"}
    created = next(row for row in rows if row.action == "open_api.service_account.create")
    assert created.target_type == "service_account" and created.target_id == str(account.user_id)
    assert created.operator_id == tenant_admin_payload.user_id
    assert created.audit_metadata["resource_owner_user_id"] == human_user.user_id

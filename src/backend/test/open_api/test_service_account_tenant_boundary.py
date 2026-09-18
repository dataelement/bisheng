"""A service account and its keys belong to exactly one tenant.

``service_account`` is a tenant-aware table, so every management read already
went through the global tenant filter — but for a child-tenant caller that
filter injects the F012 IN-list ``tenant_id IN (leaf, ROOT)``, which exists so
Root can share resources downwards. Service accounts are not shared: a child
tenant's administrator could otherwise list a Root account, open it, and issue
keys against it (the key rows land in Root's tenant, because issuance uses
``account.tenant_id``). PRD §4.2.5 / AC-5 and release-contract INV-29 / INV-31
require the opposite — a cross-tenant lookup answers exactly like a missing one.
"""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.open_api import ServiceAccountNotFoundError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_admin_scope_tenant_id,
)
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.api.endpoints import service_account as account_endpoints
from bisheng.open_api.api.endpoints import service_account_keys as key_endpoints
from bisheng.open_api.domain.repositories.service_account_repository import (
    ServiceAccountRepository,
    current_tenant_scope,
)
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest, KeyUpdateRequest
from bisheng.open_api.domain.schemas.service_account import ServiceAccountCreate, ServiceAccountUpdate
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.permission.domain.schemas import GrantMutationRequest
from bisheng.user.domain.models.user import User

ROOT_TENANT = 1
CHILD_TENANT = 5


def actor(user_id=2, tenant_id=ROOT_TENANT, *, is_global_super=False):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id, is_global_super=is_global_super)


async def seed_user(open_api_db, user_id: int, tenant_id: int):
    async with open_api_db() as session:
        session.add(User(user_id=user_id, user_name=f"user-{user_id}", password="x", delete=0))
        session.add(UserTenant(user_id=user_id, tenant_id=tenant_id, status="active", is_active=1))
        await session.commit()


async def seed_account(open_api_db, *, tenant_id: int, owner_user_id: int, name: str):
    await seed_user(open_api_db, owner_user_id, tenant_id)
    token = current_tenant_id.set(tenant_id)
    try:
        return await ServiceAccountService.create(
            actor(tenant_id=tenant_id),
            ServiceAccountCreate(name=name, resource_owner_user_id=owner_user_id),
        )
    finally:
        current_tenant_id.reset(token)


@pytest.fixture
async def two_tenant_accounts(open_api_db, fake_redis, audit_events):
    """One account in Root and one in a child tenant, both enabled."""

    root = await seed_account(open_api_db, tenant_id=ROOT_TENANT, owner_user_id=10, name="root-account")
    child = await seed_account(open_api_db, tenant_id=CHILD_TENANT, owner_user_id=20, name="child-account")
    return root, child


async def test_child_tenant_admin_cannot_read_a_root_account(open_api_db, two_tenant_accounts):
    root, child = two_tenant_accounts
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        with pytest.raises(ServiceAccountNotFoundError):
            await ServiceAccountService.get_row(root.id)
        with pytest.raises(ServiceAccountNotFoundError):
            await ServiceAccountService.get_detail(root.id)
        assert await ServiceAccountRepository.get(root.id) is None
        # The caller's own account stays fully readable.
        assert (await ServiceAccountService.get_row(child.id)).id == child.id
        assert (await ServiceAccountService.get_detail(child.id)).tenant_id == CHILD_TENANT
    finally:
        current_tenant_id.reset(token)


async def test_child_tenant_admin_cannot_mutate_a_root_account(open_api_db, two_tenant_accounts):
    root, _child = two_tenant_accounts
    admin = actor(user_id=99, tenant_id=CHILD_TENANT)
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.update_service_account(root.id, ServiceAccountUpdate(name="stolen"), admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.disable_service_account(root.id, admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.enable_service_account(root.id, admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.delete_service_account(root.id, admin)
    finally:
        current_tenant_id.reset(token)

    # Nothing was renamed, disabled or soft-deleted behind the tenant boundary.
    with bypass_tenant_filter():
        untouched = await ServiceAccountRepository.get(root.id)
    assert untouched is not None
    assert (untouched.name, untouched.disabled_at, untouched.deleted_at) == ("root-account", None, None)


async def test_child_tenant_admin_cannot_reach_a_root_accounts_keys(open_api_db, two_tenant_accounts):
    root, _child = two_tenant_accounts
    admin = actor(user_id=99, tenant_id=CHILD_TENANT)
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.list_keys(root.id, admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.filter_delegate_candidates(root.id, [], admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.issue_key(root.id, KeyIssueRequest(name="stolen-key"), admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.update_key(root.id, 1, KeyUpdateRequest(name="renamed"), admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.revoke_key(root.id, 1, admin)
        with pytest.raises(ServiceAccountNotFoundError):
            await key_endpoints.revoke_all_keys(root.id, admin)
    finally:
        current_tenant_id.reset(token)


async def test_child_tenant_admin_cannot_grant_resources_to_a_root_account(open_api_db, two_tenant_accounts):
    root, _child = two_tenant_accounts
    admin = actor(user_id=99, tenant_id=CHILD_TENANT)
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        # Each endpoint looks the account up first, so the permission port is never called.
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.list_service_account_resource_grants(root.id, _admin=admin, api=None)
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.list_service_account_grantable_resources(
                root.id, resource_type=None, keyword=None, _admin=admin, api=None
            )
        with pytest.raises(ServiceAccountNotFoundError):
            await account_endpoints.mutate_service_account_resource_grants(
                root.id,
                # Never inspected: the lookup rejects the account before the body is read.
                GrantMutationRequest.model_construct(),
                resource_type="knowledge",
                resource_id="1",
                admin=admin,
                api=None,
            )
    finally:
        current_tenant_id.reset(token)


async def test_get_by_ids_never_resolves_another_tenants_account(open_api_db, two_tenant_accounts):
    root, child = two_tenant_accounts
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        rows = await ServiceAccountRepository.get_by_ids([root.id, child.id])
    finally:
        current_tenant_id.reset(token)
    assert [row.id for row in rows] == [child.id]


async def test_list_page_total_is_filtered_the_same_way_as_data(open_api_db, two_tenant_accounts):
    root, child = two_tenant_accounts
    await seed_account(open_api_db, tenant_id=ROOT_TENANT, owner_user_id=11, name="root-account-2")

    token = current_tenant_id.set(CHILD_TENANT)
    try:
        page = await ServiceAccountService.list_page(keyword=None, page=1, page_size=20)
    finally:
        current_tenant_id.reset(token)
    # ``total`` used to be counted over an anonymous subquery, which the tenant
    # filter cannot see into — it reported every tenant's rows while ``data``
    # carried only the caller's, so the paginator offered pages that render empty.
    assert page.total == len(page.data) == 1
    assert [item.id for item in page.data] == [child.id]

    token = current_tenant_id.set(ROOT_TENANT)
    try:
        root_page = await ServiceAccountService.list_page(keyword=None, page=1, page_size=20)
    finally:
        current_tenant_id.reset(token)
    assert root_page.total == len(root_page.data) == 2
    assert child.id not in {item.id for item in root_page.data}
    assert root.id in {item.id for item in root_page.data}


async def test_global_super_admin_follows_the_active_admin_scope(open_api_db, two_tenant_accounts):
    """Same rule as the personal-token ledger: the scope decides the tenant.

    ``get_current_tenant_id()`` already folds the F019 admin-scope override in,
    so a super admin who has not switched scope manages their own tenant only —
    exactly what ``personal_token_admin._tenant_id`` does for the PAT ledger.
    """

    root, child = two_tenant_accounts
    token = current_tenant_id.set(ROOT_TENANT)
    try:
        assert (await ServiceAccountService.get_row(root.id)).id == root.id
        with pytest.raises(ServiceAccountNotFoundError):
            await ServiceAccountService.get_row(child.id)

        set_admin_scope_tenant_id(CHILD_TENANT)
        try:
            assert (await ServiceAccountService.get_row(child.id)).id == child.id
            with pytest.raises(ServiceAccountNotFoundError):
                await ServiceAccountService.get_row(root.id)
            page = await ServiceAccountService.list_page(keyword=None, page=1, page_size=20)
            assert page.total == len(page.data) == 1
            assert [item.id for item in page.data] == [child.id]
        finally:
            set_admin_scope_tenant_id(None)
    finally:
        current_tenant_id.reset(token)


async def test_execution_and_validation_reads_keep_their_cross_tenant_access(open_api_db, two_tenant_accounts):
    """The boundary is a management-surface rule, not a global one.

    Bearer validation resolves the account behind a key before any tenant
    context exists and compares ``tenant_id`` against the credential itself;
    the execution path reads it under an explicit bypass. Neither may be
    narrowed by the caller's (absent) tenant, or every child-tenant key stops
    authenticating.
    """

    root, _child = two_tenant_accounts
    token = current_tenant_id.set(CHILD_TENANT)
    try:
        with bypass_tenant_filter():
            assert current_tenant_scope() is None
            assert (await ServiceAccountRepository.get(root.id)).id == root.id
    finally:
        current_tenant_id.reset(token)

    no_context = current_tenant_id.set(None)
    try:
        assert current_tenant_scope() is None
    finally:
        current_tenant_id.reset(no_context)

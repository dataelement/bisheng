"""Admin listing is a concrete-tenant capability, separate from creation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.admin_scope import AdminScopeTenantRequiredError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def listing(tenant_context):
    tenant_context(101)
    repository = SimpleNamespace(
        alist_admin=AsyncMock(
            return_value=([Knowledge(id=3, tenant_id=101, user_id=99, name="Not joined", type=3)], 17)
        ),
    )
    user = SimpleNamespace(user_id=7, tenant_id=101, is_admin=lambda: True)
    service = KnowledgeSpaceService(None, user, space_listing_repository=repository)
    service._permission_actor = AsyncMock(return_value=PermissionActor(user_id=7, current_tenant_id=101))
    service._check_action = AsyncMock(side_effect=AssertionError("admin rows are not a visible/edit subset"))
    return service, repository


@pytest.mark.parametrize("role", ["super", "tenant"])
async def test_only_actual_admins_list_all_selected_tenant_rows_without_visible_or_pin_filter(listing, role):
    service, repository = listing
    service._permission_actor.return_value = PermissionActor(
        user_id=7,
        current_tenant_id=101,
        super_admin=role == "super",
        tenant_admin_tenant_ids=frozenset({101}) if role == "tenant" else frozenset(),
    )
    with management_tenant_scope(101):
        result = await service.list_admin_spaces(keyword="Not", page=2, page_size=10)
    assert result.total == 17 and [row.id for row in result.data] == [3]
    repository.alist_admin.assert_awaited_once_with(keyword="Not", page=2, page_size=10)
    service._check_action.assert_not_awaited()
    assert service.login_user.tenant_id == 101


@pytest.mark.parametrize("claim", ["menu", "owner", "resource_manager", "department_admin", "other_tenant_admin"])
async def test_creation_menu_owner_and_department_roles_do_not_grant_admin_list(listing, claim):
    service, repository = listing
    service.login_user.claim = claim
    service._permission_actor.return_value = PermissionActor(
        user_id=7,
        current_tenant_id=101,
        tenant_admin_tenant_ids=frozenset({202}) if claim == "other_tenant_admin" else frozenset(),
    )
    with management_tenant_scope(101), pytest.raises(PermissionDeniedError):
        await service.list_admin_spaces()
    repository.alist_admin.assert_not_awaited()


@pytest.mark.parametrize("scope", [None, 0, -1])
async def test_admin_list_rejects_missing_or_non_concrete_management_scope(listing, monkeypatch, scope):
    service, repository = listing
    service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    monkeypatch.setattr(module, "get_admin_scope_tenant_id", lambda: scope, raising=False)
    with management_tenant_scope(101), pytest.raises(AdminScopeTenantRequiredError):
        await service.list_admin_spaces()
    repository.alist_admin.assert_not_awaited()


@pytest.mark.parametrize(
    "actor",
    [
        PermissionActor(user_id=7, current_tenant_id=202, super_admin=True),
        PermissionActor(user_id=7, current_tenant_id=101, super_admin=True, data_scope=DATA_SCOPE_PERSONAL),
    ],
)
async def test_admin_identity_does_not_override_current_tenant_or_credential_narrowing(listing, actor):
    service, repository = listing
    service._permission_actor.return_value = actor
    with management_tenant_scope(101), pytest.raises(PermissionDeniedError):
        await service.list_admin_spaces()
    repository.alist_admin.assert_not_awaited()


async def test_super_selected_tenant_does_not_rewrite_identity_home_tenant(listing):
    service, _ = listing
    service.login_user.tenant_id = 1
    service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    with management_tenant_scope(101):
        result = await service.list_admin_spaces()
    assert result.data[0].tenant_id == 101 and service.login_user.tenant_id == 1


@pytest.mark.parametrize("query", [{"page": 0}, {"page_size": 0}, {"page_size": 201}])
async def test_admin_list_internal_pagination_is_bounded(listing, query):
    service, repository = listing
    service._permission_actor.return_value = PermissionActor(user_id=7, current_tenant_id=101, super_admin=True)
    with management_tenant_scope(101), pytest.raises(ValueError):
        await service.list_admin_spaces(**query)
    repository.alist_admin.assert_not_awaited()

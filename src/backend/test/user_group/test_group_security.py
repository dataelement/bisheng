"""Security regressions for both legacy group response and membership sinks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.api.services import role_group_service as legacy
from bisheng.api.v1.usergroup import router
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.user_group import UserGroupNotFoundError, UserGroupPermissionDeniedError
from bisheng.database.models.group import Group
from bisheng.user.domain.models.user import User
from bisheng.user_group.domain.services import user_group_service as domain


def actor(*, admin=False, tenant_id=1):
    return SimpleNamespace(
        user_id=101, user_name="operator", tenant_id=tenant_id, user_role=[1] if admin else [2], is_admin=lambda: admin
    )


@pytest.fixture(autouse=True)
def active_tenant_members(monkeypatch):
    from bisheng.user_group.domain.repositories.member_identity_repository import MemberIdentityRepository

    monkeypatch.setattr(
        MemberIdentityRepository, "tenant_member_ids", AsyncMock(side_effect=lambda ids, tenant_id: set(ids))
    )


@pytest.fixture
def sensitive_user():
    return User(
        user_id=202,
        user_name="member",
        password="x" * 32,
        email="private@example.test",
        phone_number="private-phone",
        external_id="private-id",
        token_version=7,
        avatar="avatar/object",
    )


def test_shared_group_user_serializer_is_an_allowlist(monkeypatch, sensitive_user):
    monkeypatch.setattr(legacy.UserService, "get_avatar_share_link_sync", lambda _: "shared-avatar")
    result = legacy.RoleGroupService._dump_user_with_avatar_share_link(sensitive_user)
    assert result == {"user_id": 202, "user_name": "member", "avatar": "shared-avatar"}
    assert sensitive_user.avatar == "avatar/object"
    assert legacy.RoleGroupService._dump_user_with_avatar_share_link(None) == {}


def test_group_list_admins_use_safe_projection(monkeypatch, sensitive_user):
    monkeypatch.setattr(legacy.UserGroupDao, "get_groups_admins", lambda _: [SimpleNamespace(user_id=202, group_id=10)])
    monkeypatch.setattr(legacy.UserDao, "get_user_by_ids", lambda _: [sensitive_user])
    monkeypatch.setattr(legacy.UserService, "get_avatar_share_link_sync", lambda _: None)
    result = legacy.RoleGroupService().enrich_group_reads([Group(id=10, group_name="A")])
    assert result[0].group_admins == [{"user_id": 202, "user_name": "member", "avatar": None}]


def test_legacy_roster_checks_domain_group_visibility(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: actor()
    monkeypatch.setattr(domain.GroupDao, "aget_by_id", AsyncMock(return_value=Group(id=20, group_name="private")))
    monkeypatch.setattr(domain, "_user_can_view_group", AsyncMock(return_value=False))
    roster = MagicMock(return_value=[])
    monkeypatch.setattr(legacy.UserGroupDao, "get_group_user", roster)
    # Domain errors propagate here; the real app's handler renders their business code.
    with TestClient(app) as client, pytest.raises(UserGroupPermissionDeniedError):
        client.get("/api/v1/group/get_group_user?group_id=20")
    roster.assert_not_called()


def test_public_roster_response_is_safe(monkeypatch, sensitive_user):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: actor()
    monkeypatch.setattr(
        domain.GroupDao,
        "aget_by_id",
        AsyncMock(return_value=Group(id=20, group_name="public", tenant_id=1, visibility="public")),
    )
    monkeypatch.setattr(domain, "_can_view_all_groups", AsyncMock(return_value=False))
    monkeypatch.setattr(legacy.UserGroupDao, "get_group_user", lambda *args: [SimpleNamespace(user_id=202)])
    monkeypatch.setattr(legacy.UserDao, "get_user_by_ids", lambda _: [sensitive_user])
    monkeypatch.setattr(legacy.UserService, "get_avatar_share_link_sync", lambda _: None)
    with TestClient(app) as client:
        result = client.get("/api/v1/group/get_group_user?group_id=20&page_size=10&page_num=1").json()
    assert result["status_code"] == 200
    assert result["data"] == [{"user_id": 202, "user_name": "member", "avatar": None}]


@pytest.fixture
def membership_boundary(monkeypatch):
    monkeypatch.setattr(legacy.UserRoleDao, "get_user_roles", lambda _: [])
    monkeypatch.setattr(
        legacy.UserGroupDao, "get_user_group", lambda _: [SimpleNamespace(group_id=10), SimpleNamespace(group_id=99)]
    )
    monkeypatch.setattr(
        legacy.UserGroupDao,
        "get_user_admin_group",
        lambda _: [SimpleNamespace(group_id=10), SimpleNamespace(group_id=11)],
    )
    monkeypatch.setattr(legacy.GroupDao, "get_group_by_ids", lambda ids: [Group(id=i, group_name=str(i)) for i in ids])
    monkeypatch.setattr(legacy.AuditLogService, "update_user", MagicMock())
    monkeypatch.setattr(legacy, "get_request_ip", lambda _: "test")
    add, remove, project = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(legacy.UserGroupDao, "add_user_groups", add)
    monkeypatch.setattr(legacy.UserGroupDao, "delete_user_groups", remove)
    monkeypatch.setattr(legacy.RoleGroupService, "_execute_group_change_ops", project)
    return add, remove, project


def test_foreign_group_addition_denied_before_any_write(monkeypatch, membership_boundary):
    async def validate(user, user_id, group_ids, **kwargs):
        if 20 in group_ids:
            raise UserGroupPermissionDeniedError()

    # Keep the actual delta algorithm under test, not the policy adapter itself.
    monkeypatch.setattr(domain.UserGroupService, "avalidate_legacy_membership_changes", validate, raising=False)
    with pytest.raises(UserGroupPermissionDeniedError):
        legacy.RoleGroupService().replace_user_groups(None, actor(), 202, [11, 20])
    for effect in membership_boundary:
        effect.assert_not_called()


def test_mixed_batch_real_group_policy_denies_before_deleting(monkeypatch, membership_boundary):
    monkeypatch.setattr(
        domain.GroupDao,
        "aget_by_id",
        AsyncMock(
            side_effect=lambda gid: Group(
                id=gid, group_name=str(gid), tenant_id=1, visibility="private", create_user=999
            )
        ),
    )
    relation = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "bisheng.permission.application.get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(check=relation)),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service._is_tenant_admin", AsyncMock(return_value=False)
    )
    # Deletion of A and addition to administered C are allowed, but foreign B
    # must reject the entire request before either database or tuple effects.
    with pytest.raises(UserGroupPermissionDeniedError):
        legacy.RoleGroupService().replace_user_groups(None, actor(), 202, [11, 20])
    for effect in membership_boundary:
        effect.assert_not_called()


def test_legacy_replacement_preserves_unmanaged_memberships_and_deduplicates(monkeypatch, membership_boundary):
    validate = AsyncMock()
    monkeypatch.setattr(domain.UserGroupService, "avalidate_legacy_membership_changes", validate, raising=False)
    legacy.RoleGroupService().replace_user_groups(None, actor(), 202, [11, 11, 99])
    add, remove, project = membership_boundary
    add.assert_called_once_with(202, [11])
    remove.assert_called_once_with(202, [10])
    validate.assert_awaited_once()
    assert set(validate.await_args.args[2]) == {10, 11}
    project.assert_called_once()


@pytest.mark.parametrize("visibility,allowed", [("public", True), ("private", False)])
async def test_existing_domain_visibility_contract(monkeypatch, visibility, allowed):
    monkeypatch.setattr(domain, "_can_view_all_groups", AsyncMock(return_value=False))
    monkeypatch.setattr(domain.UserGroupDao, "aget_user_visible_group_ids", AsyncMock(return_value=[]))
    group = Group(id=20, group_name="B", tenant_id=1, visibility=visibility, create_user=999)
    assert await domain._user_can_view_group(actor(), group) is allowed


@pytest.mark.parametrize("kind", ["creator", "member", "admin"])
async def test_private_group_legitimate_visibility_is_preserved(monkeypatch, kind):
    monkeypatch.setattr(domain, "_can_view_all_groups", AsyncMock(return_value=kind == "admin"))
    monkeypatch.setattr(
        domain.UserGroupDao, "aget_user_visible_group_ids", AsyncMock(return_value=[20] if kind == "member" else [])
    )
    group = Group(
        id=20, group_name="B", tenant_id=1, visibility="private", create_user=101 if kind == "creator" else 999
    )
    assert await domain._user_can_view_group(actor(), group)


@pytest.mark.parametrize(
    "group_tenant,delegated,relation_allowed,expected",
    [(1, True, True, True), (1, True, False, False), (2, True, True, False), (1, False, True, False)],
)
async def test_target_group_authority_is_not_managed_user_authority(
    monkeypatch, group_tenant, delegated, relation_allowed, expected
):
    group = Group(id=20, group_name="B", tenant_id=group_tenant, visibility="private", create_user=999)
    monkeypatch.setattr(domain.GroupDao, "aget_by_id", AsyncMock(return_value=group))
    relation = AsyncMock(return_value=relation_allowed)
    monkeypatch.setattr(
        "bisheng.permission.application.get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(check=relation)),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service._is_tenant_admin", AsyncMock(return_value=False)
    )
    if expected:
        await domain.UserGroupService.avalidate_legacy_membership_changes(
            actor(), 202, [20], delegated_group_ids=[20] if delegated else []
        )
        assert relation.await_args.kwargs["resource"].resource_id == "20"
    else:
        with pytest.raises(UserGroupPermissionDeniedError):
            await domain.UserGroupService.avalidate_legacy_membership_changes(
                actor(), 202, [20], delegated_group_ids=[20] if delegated else []
            )


async def test_missing_target_group_fails_closed(monkeypatch):
    monkeypatch.setattr(domain.GroupDao, "aget_by_id", AsyncMock(return_value=None))
    with pytest.raises(UserGroupNotFoundError):
        await domain.UserGroupService.aensure_group_visible(20, actor())
    with pytest.raises(UserGroupNotFoundError):
        await domain.UserGroupService.avalidate_legacy_membership_changes(
            actor(admin=True), 202, [20], delegated_group_ids=[]
        )


async def test_global_admin_target_group_flow_is_preserved(monkeypatch):
    monkeypatch.setattr(
        domain.GroupDao, "aget_by_id", AsyncMock(return_value=Group(id=20, group_name="B", tenant_id=1))
    )
    await domain.UserGroupService.avalidate_legacy_membership_changes(
        actor(admin=True), 202, [20], delegated_group_ids=[]
    )


async def test_tenant_admin_target_personnel_scope_is_checked(monkeypatch):
    monkeypatch.setattr(
        domain.GroupDao, "aget_by_id", AsyncMock(return_value=Group(id=20, group_name="B", tenant_id=1))
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service._is_tenant_admin", AsyncMock(return_value=True)
    )
    tenant_scope = AsyncMock(side_effect=UserGroupPermissionDeniedError())
    monkeypatch.setattr(domain, "_ensure_tenant_member_scope", tenant_scope)
    with pytest.raises(UserGroupPermissionDeniedError):
        await domain.UserGroupService.avalidate_legacy_membership_changes(actor(), 202, [20], delegated_group_ids=[])
    tenant_scope.assert_awaited_once()

"""Tenant administrators enter management without fabricated ordinary grants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.user.domain.services.auth import LoginUser
from bisheng.user.domain.services.user import UserService
from test.fixtures.managed_tenant import management_scope


@pytest.fixture
def access(monkeypatch):
    policy = SimpleNamespace(
        user_id=674, home_tenant_id=20, role_ids=(), roles=(), web_menu=frozenset(), is_identity_admin=False
    )
    monkeypatch.setattr("bisheng.role.application.effective_roles.load_effective_roles", AsyncMock(return_value=policy))
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr("bisheng.permission.application.is_tenant_admin", checker)
    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "bisheng.approval.domain.services.user_menu_access_service.UserMenuAccessService.list_effective_menu_grants",
        AsyncMock(return_value=[]),
    )
    return SimpleNamespace(policy=policy, checker=checker, user=SimpleNamespace(user_id=674))


async def test_child_admin_with_zero_ordinary_roles_can_login_and_enter_management(access):
    access.checker.return_value = True
    with management_scope(home=20, target=60):
        assert await UserService._reject_login_if_user_has_no_usable_access(access.user) is None
        roles, menu = await LoginUser.get_roles_web_menu(access.user)
        entry = await LoginUser.user_entry_payload_for_read(access.user)
    assert roles == []
    assert {"admin", "sys", "system_config", "build", "create_app"}.issubset(menu)
    assert "workstation" not in menu
    assert entry == {"has_workbench": False, "has_admin_console": True, "default_entry": "platform"}
    assert all(call.args == (674, 20) for call in access.checker.await_args_list)
    assert access.policy.role_ids == () and access.policy.web_menu == frozenset()


async def test_child_admin_with_workbench_role_still_prefers_management(access):
    access.checker.return_value = True
    access.policy.role_ids = (2,)
    access.policy.web_menu = frozenset({"workstation", "home"})
    entry = await LoginUser.user_entry_payload_for_read(access.user)
    assert entry == {"has_workbench": True, "has_admin_console": True, "default_entry": "platform"}


async def test_revoked_or_foreign_tenant_admin_cannot_enter(access):
    with management_scope(home=20, target=60):
        rejected = await UserService._reject_login_if_user_has_no_usable_access(access.user)
        _, menu = await LoginUser.get_roles_web_menu(access.user)
        entry = await LoginUser.user_entry_payload_for_read(access.user)
    assert rejected.status_code == UserNoRoleForLoginError.Code
    assert not ({"sys", "system_config", "admin"} & set(menu))
    assert entry["has_admin_console"] is False
    assert all(call.args == (674, 20) for call in access.checker.await_args_list)


async def test_permission_failure_is_not_treated_as_verified_admin(access):
    access.checker.side_effect = RuntimeError("permission backend unavailable")
    with pytest.raises(RuntimeError, match="permission backend unavailable"):
        await UserService._reject_login_if_user_has_no_usable_access(access.user)
    with pytest.raises(RuntimeError):
        await LoginUser.user_entry_payload_for_read(access.user)


async def test_root_and_platform_admin_do_not_need_child_admin_lookup(access):
    access.policy.home_tenant_id = 1
    rejected = await UserService._reject_login_if_user_has_no_usable_access(access.user)
    assert rejected.status_code == UserNoRoleForLoginError.Code
    access.policy.is_identity_admin = True
    assert await UserService._reject_login_if_user_has_no_usable_access(access.user) is None
    access.checker.assert_not_awaited()


async def test_ordinary_role_and_no_menu_are_not_confused(access):
    access.policy.role_ids = (2,)
    rejected = await UserService._reject_login_if_user_has_no_usable_access(access.user)
    assert rejected.status_code == UserNoWebMenuForLoginError.Code
    access.policy.web_menu = frozenset({"workstation", "home"})
    assert await UserService._reject_login_if_user_has_no_usable_access(access.user) is None
    entry = await LoginUser.user_entry_payload_for_read(access.user)
    assert entry == {"has_workbench": True, "has_admin_console": False, "default_entry": "workspace"}


async def test_revocation_is_visible_on_the_next_read(access):
    access.checker.return_value = True
    assert (await LoginUser.user_entry_payload_for_read(access.user))["has_admin_console"]
    access.checker.return_value = False
    assert not (await LoginUser.user_entry_payload_for_read(access.user))["has_admin_console"]


async def test_child_admin_does_not_become_platform_super_admin(access, monkeypatch):
    access.checker.return_value = True
    identity = LoginUser(user_id=674, user_role=[], tenant_id=20)
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=identity))
    assert await UserService._reject_login_if_user_has_no_usable_access(access.user) is None
    assert not identity.is_admin()
    with pytest.raises(HTTPException) as rejected:
        await LoginUser.get_admin_user(None)
    assert rejected.value.status_code == 403


async def test_user_info_exposes_child_admin_and_management_entry_together(access, monkeypatch):
    from bisheng.database.models.tenant import TenantDao, UserTenantDao
    from bisheng.user.api.user import get_info
    from bisheng.user.domain.models.user import UserDao

    access.checker.return_value = True
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=access.user))
    monkeypatch.setattr(UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=SimpleNamespace(tenant_id=20)))
    monkeypatch.setattr(TenantDao, "aget_by_id", AsyncMock(return_value=SimpleNamespace(tenant_name="child")))
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "bisheng.permission.application.get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(check=AsyncMock(return_value=True))),
    )

    async def payload(user, **fields):
        return fields

    monkeypatch.setattr(UserService, "build_user_read", payload)
    identity = LoginUser(user_id=674, user_name="child", user_role=[], tenant_id=20)
    identity._role_policy = access.policy
    response = await get_info(identity)
    assert response.data["is_child_admin"] is True
    assert response.data["has_admin_console"] is True
    assert response.data["has_workbench"] is False
    assert response.data["default_entry"] == "platform"
    assert response.data["role"] == "[]"
    await LoginUser.assert_effective_web_menu_contains(674, "sys")


async def test_child_admin_creation_uses_verified_home_policy_and_revocation(access, monkeypatch):
    from bisheng.database.models.department import DepartmentDao
    from bisheng.user.domain.models.user import UserDao

    identity = LoginUser(user_id=674, user_role=[], tenant_id=20)
    monkeypatch.setattr(LoginUser, "get_login_user", AsyncMock(return_value=identity))
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=access.user))
    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    access.checker.return_value = True
    with management_scope(home=20, target=60):
        assert await LoginUser.get_app_creator_user(None) is identity
    assert all(call.args == (674, 20) for call in access.checker.await_args_list)
    assert not identity.is_admin() and access.policy.role_ids == ()
    access.checker.return_value = False
    with pytest.raises(HTTPException):
        await LoginUser.get_app_creator_user(None)


async def test_department_admin_does_not_inherit_tenant_application_creation(access):
    _, menu = await LoginUser.get_roles_web_menu(access.user, is_department_admin=True)
    assert "create_app" not in menu
    assert "build" not in menu

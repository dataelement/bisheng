"""F009 AC-15/16/18/19: login and menus use current home policy, never M."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import delete

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.services.auth import LoginUser
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def ordinary_policy(policy_db, monkeypatch):
    import bisheng.user.domain.models.user_role as module

    monkeypatch.setattr(module, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(module, "get_sync_db_session", policy_db.sync_sessions)
    monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            await session.commit()
    return policy_db


async def test_login_does_not_trust_foreign_or_supplied_roles(ordinary_policy):
    """AC-15/16: supplied role IDs cannot forge identity or bypass E."""
    with management_scope(home=2, target=3):
        user = await LoginUser.init_login_user(77, "policy", tenant_id=2, role_ids=[1, 4])
        assert user.user_role == [2, 3] and user.tenant_id == 2 and not user.is_admin()
        sync_user = LoginUser.init_login_user_sync(77, "policy", tenant_id=2)
        assert sync_user.user_role == [2, 3] and not sync_user.is_admin()


async def test_menu_uses_definition_owner_and_personal_home(ordinary_policy, monkeypatch):
    """AC-16/19: WEB_MENU from O plus H personal grant, no M or resource grant."""
    from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService

    grants = AsyncMock(return_value=["admin"])
    monkeypatch.setattr(UserMenuAccessService, "list_effective_menu_grants", grants)
    with management_scope(home=2, target=3):
        roles, menu = await LoginUser.get_roles_web_menu(SimpleNamespace(user_id=77), role_ids=[4])
    assert roles == [2, 3]
    assert set(menu) == {"admin", "tool", "knowledge"}
    grants.assert_awaited_once_with(2, 77)


async def test_login_access_gate_does_not_accept_a_supplied_admin_role(ordinary_policy, monkeypatch):
    """AC-15/18: entry arguments do not replace verified identity/roles."""
    from bisheng.common.errcode.user import UserNoRoleForLoginError
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.user.domain.services.user import UserService

    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    response = await UserService._reject_login_if_user_has_no_usable_access(
        SimpleNamespace(user_id=78), role_ids=[1], is_department_admin=False
    )
    assert response.status_code == UserNoRoleForLoginError.Code

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.approval.domain.services.user_menu_access_service as user_menu_access_service_module
import bisheng.user.domain.services.auth as auth_module


def test_expand_menu_keys_with_dependencies_adds_parent_entries():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService
    keys = UserMenuAccessService.expand_menu_keys_with_dependencies(['create_knowledge'])

    assert keys == ['admin', 'knowledge', 'create_knowledge']


@pytest.mark.asyncio
async def test_get_roles_web_menu_includes_personal_menu_grants():
    LoginUser = importlib.reload(auth_module).LoginUser
    user = SimpleNamespace(user_id=7, tenant_id=3)
    role_rows = [SimpleNamespace(role_id=2)]
    role_access_rows = [SimpleNamespace(third_id='apps')]

    with patch(
        'bisheng.user.domain.services.auth.UserRoleDao.aget_user_roles',
        new_callable=AsyncMock,
        return_value=role_rows,
    ), patch(
        'bisheng.user.domain.services.auth.RoleAccessDao.aget_role_access',
        new_callable=AsyncMock,
        return_value=role_access_rows,
    ), patch(
        'bisheng.user.domain.services.auth.UserMenuAccessService.list_effective_menu_grants',
        new_callable=AsyncMock,
        return_value=['workstation', 'home'],
    ) as mock_personal_menu:
        role, web_menu = await LoginUser.get_roles_web_menu(user, is_department_admin=False)

    assert role == [2]
    assert set(web_menu) == {'apps', 'workstation', 'home'}
    mock_personal_menu.assert_awaited_once_with(3, 7)


@pytest.mark.asyncio
async def test_get_roles_web_menu_keeps_department_admin_full_menu():
    LoginUser = importlib.reload(auth_module).LoginUser
    user = SimpleNamespace(user_id=9, tenant_id=1)

    with patch(
        'bisheng.user.domain.services.auth.UserRoleDao.aget_user_roles',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(role_id=2)],
    ), patch(
        'bisheng.user.domain.services.auth.RoleAccessDao.aget_role_access',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.user.domain.services.auth.UserMenuAccessService.list_effective_menu_grants',
        new_callable=AsyncMock,
        return_value=[],
    ):
        _, web_menu = await LoginUser.get_roles_web_menu(user, is_department_admin=True)

    assert 'system_config' in web_menu
    assert 'sys' in web_menu
    assert 'workstation' in web_menu

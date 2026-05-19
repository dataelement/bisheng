import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.approval.domain.services.user_menu_access_service as user_menu_access_service_module
import bisheng.user.domain.services.auth as auth_module
from bisheng.common.errcode.approval import ApprovalMenuApplyDisabledError


def test_expand_menu_keys_with_dependencies_adds_parent_entries():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService
    keys = UserMenuAccessService.expand_menu_keys_with_dependencies(['create_knowledge'])

    assert keys == ['admin', 'knowledge', 'create_knowledge']


def test_menu_apply_is_rejected_when_mode_disabled():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService

    with pytest.raises(ApprovalMenuApplyDisabledError):
        UserMenuAccessService.ensure_application_allowed(menu_approval_mode=False, has_menu_access=False)


def test_menu_apply_is_rejected_when_user_already_has_access():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService

    with pytest.raises(ApprovalMenuApplyDisabledError):
        UserMenuAccessService.ensure_application_allowed(menu_approval_mode=True, has_menu_access=True)


@pytest.mark.asyncio
async def test_grant_menu_access_writes_leaf_and_parent_dependencies():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService

    recorded = []

    async def _fake_upsert(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(**kwargs)

    with patch(
        'bisheng.approval.domain.services.user_menu_access_service.UserMenuAccessRepository.upsert_active_grant',
        new=_fake_upsert,
    ):
        rows = await UserMenuAccessService.grant_menu_access(
            tenant_id=1,
            user_id=7,
            menu_key='create_knowledge',
            menu_name='新建知识库',
            grant_source='approval_instance',
            grant_instance_id=99,
        )

    assert [row.menu_key for row in rows] == ['admin', 'knowledge', 'create_knowledge']
    assert recorded[-1]['menu_name'] == '新建知识库'
    assert recorded[0]['menu_name'] is None


@pytest.mark.asyncio
async def test_revoke_menu_access_records_revoke_on_leaf_first():
    UserMenuAccessService = importlib.reload(user_menu_access_service_module).UserMenuAccessService

    recorded = []

    async def _fake_revoke(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(**kwargs)

    with patch(
        'bisheng.approval.domain.services.user_menu_access_service.UserMenuAccessRepository.revoke_grant',
        new=_fake_revoke,
    ):
        rows = await UserMenuAccessService.revoke_menu_access(
            tenant_id=1,
            user_id=7,
            menu_key='create_knowledge',
            grant_source='approval_instance',
            revoked_by_user_id=1,
            revoked_reason='manual revoke',
        )

    assert [row.menu_key for row in rows] == ['create_knowledge', 'knowledge', 'admin']
    assert recorded[0]['revoked_reason'] == 'manual revoke'
    assert recorded[-1]['revoked_reason'] is None


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

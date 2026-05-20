import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.approval.domain.services.user_menu_access_service as user_menu_access_service_module
import bisheng.approval.domain.services.approval_center_service as approval_center_service_module
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
async def test_apply_menu_access_request_uses_gate_when_mode_enabled():
    ApprovalCenterService = importlib.reload(approval_center_service_module).ApprovalCenterService
    login_user = SimpleNamespace(user_id=7, user_name='alice', tenant_id=1)
    db_user = SimpleNamespace(user_id=7, tenant_id=1)

    with patch(
        'bisheng.approval.domain.services.approval_center_service.UserDao.aget_user',
        new_callable=AsyncMock,
        return_value=db_user,
    ), patch(
        'bisheng.approval.domain.services.approval_center_service.DepartmentDao.aget_user_admin_departments',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.approval.domain.services.approval_center_service.LoginUser.get_roles_web_menu',
        new_callable=AsyncMock,
        return_value=([2], ['apps']),
    ), patch(
        'bisheng.approval.domain.services.approval_center_service.LoginUser.compute_menu_approval_mode',
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        'bisheng.approval.domain.services.approval_center_service.ApprovalGate.request_or_pass',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(model_dump=lambda: {'decision': 'pending', 'instance_id': 99}),
    ) as mock_request:
        result = await ApprovalCenterService.apply_menu_access_request(
            login_user=login_user,
            menu_key='knowledge',
            menu_name='知识管理',
            reason='need access',
        )

    assert result['instance_id'] == 99
    req = mock_request.await_args.kwargs if mock_request.await_args and mock_request.await_args.kwargs else mock_request.await_args.args[0]
    assert req.scenario_code == 'menu_access_request'
    assert req.payload_snapshot['menu_key'] == 'knowledge'


@pytest.mark.asyncio
async def test_revoke_menu_grant_uses_instance_payload_menu_key():
    ApprovalCenterService = importlib.reload(approval_center_service_module).ApprovalCenterService

    with patch(
        'bisheng.approval.domain.services.approval_center_service.ApprovalInstanceRepository.get_instance',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            id=22,
            tenant_id=1,
            applicant_user_id=7,
            payload_snapshot={'menu_key': 'knowledge'},
            scenario_code='menu_access_request',
        ),
    ), patch(
        'bisheng.approval.domain.services.approval_center_service.UserMenuAccessService.revoke_menu_access',
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(menu_key='knowledge')],
    ) as mock_revoke, patch(
        'bisheng.approval.domain.services.approval_center_service.ApprovalCenterService._write_audit_log',
        new_callable=AsyncMock,
    ) as mock_audit_log:
        result = await ApprovalCenterService.revoke_menu_grant(
            instance_id=22,
            operator_user_id=1,
            reason='manual revoke',
        )

    assert result['revoked_keys'] == ['knowledge']
    mock_revoke.assert_awaited_once()
    mock_audit_log.assert_awaited_once()


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

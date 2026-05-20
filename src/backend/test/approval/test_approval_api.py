from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

for mod in ('celery', 'celery.schedules', 'celery.app', 'celery.app.task'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

from bisheng.approval.api.router import router as approval_router
from bisheng.common.dependencies.user_deps import UserPayload


class MockUser:
    user_id = 7
    user_name = 'alice'
    user_role = [2]
    tenant_id = 1
    group_cache = {}

    def is_admin(self):
        return False


class MockAdminUser(MockUser):
    user_id = 1
    user_name = 'admin'
    user_role = [1]

    def is_admin(self):
        return True


def _make_app(user_cls):
    app = FastAPI()
    app.include_router(approval_router, prefix='/api/v1')

    async def get_user():
        return user_cls()

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    return app


def test_user_approval_endpoints():
    app = _make_app(MockUser)
    with patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.list_my_tasks',
        new_callable=AsyncMock,
        return_value={'data': [{'task_id': 11}], 'total': 1},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.get_task_detail',
        new_callable=AsyncMock,
        return_value={'task_id': 11, 'status': 'pending'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.decide_task_api',
        new_callable=AsyncMock,
        return_value={'task_id': 11, 'status': 'approved'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.list_my_requests',
        new_callable=AsyncMock,
        return_value={'data': [{'instance_id': 21}], 'total': 1},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.get_instance_detail',
        new_callable=AsyncMock,
        return_value={'instance_id': 21, 'status': 'pending'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.withdraw_instance',
        new_callable=AsyncMock,
        return_value={'instance_id': 21, 'status': 'withdrawn'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.apply_menu_access_request',
        new_callable=AsyncMock,
        return_value={'decision': 'pending', 'instance_id': 31},
    ), patch(
        'bisheng.approval.api.endpoints.approval_user.ApprovalCenterService.revoke_menu_grant',
        new_callable=AsyncMock,
        return_value={'instance_id': 31, 'revoked_keys': ['knowledge']},
    ):
        with TestClient(app) as c:
            assert c.get('/api/v1/approval/my-tasks').json()['data']['total'] == 1
            assert c.get('/api/v1/approval/my-tasks/11').json()['data']['task_id'] == 11
            assert c.post('/api/v1/approval/tasks/11/decision', json={'action': 'approve'}).json()['data']['status'] == 'approved'
            assert c.get('/api/v1/approval/my-requests').json()['data']['total'] == 1
            assert c.get('/api/v1/approval/instances/21').json()['data']['instance_id'] == 21
            assert c.post('/api/v1/approval/instances/21/withdraw', json={'reason': 'cancel'}).json()['data']['status'] == 'withdrawn'
            assert c.post('/api/v1/approval/menu-access/apply', json={'menu_key': 'knowledge', 'menu_name': '知识管理'}).json()['data']['instance_id'] == 31
            assert c.post('/api/v1/approval/menu-access/31/revoke-grant', json={'reason': 'revoke'}).json()['data']['revoked_keys'] == ['knowledge']


def test_admin_approval_endpoints():
    app = _make_app(MockAdminUser)
    with patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_presets',
        new_callable=AsyncMock,
        return_value=[{'scenario_code': 'menu_access_request'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_scenarios',
        new_callable=AsyncMock,
        return_value=[{'id': 1, 'scenario_code': 'menu_access_request'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.create_scenario',
        new_callable=AsyncMock,
        return_value={'id': 1, 'scenario_code': 'menu_access_request'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.update_scenario',
        new_callable=AsyncMock,
        return_value={'id': 1, 'scenario_code': 'menu_access_request', 'enabled': True},
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_routes',
        new_callable=AsyncMock,
        return_value=[{'id': 9, 'route_type': 'flow'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.create_route',
        new_callable=AsyncMock,
        return_value={'id': 10, 'route_name': '默认流程', 'route_type': 'flow'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_flows',
        new_callable=AsyncMock,
        return_value=[{'id': 12, 'flow_code': 'menu_default', 'flow_name': '菜单默认流程'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.create_flow',
        new_callable=AsyncMock,
        return_value={'id': 12, 'flow_code': 'menu_default', 'flow_name': '菜单默认流程'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_nodes',
        new_callable=AsyncMock,
        return_value=[{'id': 15, 'node_code': 'n1', 'node_name': '一级审批', 'node_mode': 'or'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.create_node',
        new_callable=AsyncMock,
        return_value={'id': 15, 'node_code': 'n1', 'node_name': '一级审批', 'node_mode': 'or'},
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalScenarioAdminService.list_open_exceptions',
        new_callable=AsyncMock,
        return_value=[{'id': 88, 'exception_type': 'route_missing'}],
    ), patch(
        'bisheng.approval.api.endpoints.approval_admin.ApprovalExceptionService.retry_exception_api',
        new_callable=AsyncMock,
        return_value={'exception_id': 88, 'status': 'resolved'},
    ) as mock_retry_exception:
        with TestClient(app) as c:
            assert c.get('/api/v1/approval/admin/scenario-presets').json()['data'][0]['scenario_code'] == 'menu_access_request'
            assert c.get('/api/v1/approval/admin/scenarios').json()['data'][0]['id'] == 1
            assert c.post('/api/v1/approval/admin/scenarios', json={'scenario_code': 'menu_access_request', 'scenario_name': '菜单权限申请'}).json()['data']['id'] == 1
            assert c.put('/api/v1/approval/admin/scenarios/1', json={'enabled': True}).json()['data']['enabled'] is True
            assert c.get('/api/v1/approval/admin/scenarios/1/routes').json()['data'][0]['id'] == 9
            assert c.post('/api/v1/approval/admin/scenarios/1/routes', json={'route_name': '默认流程', 'route_type': 'flow'}).json()['data']['id'] == 10
            assert c.get('/api/v1/approval/admin/scenarios/1/flows').json()['data'][0]['id'] == 12
            assert c.post('/api/v1/approval/admin/scenarios/1/flows', json={'flow_code': 'menu_default', 'flow_name': '菜单默认流程'}).json()['data']['id'] == 12
            assert c.get('/api/v1/approval/admin/flows/12/nodes').json()['data'][0]['id'] == 15
            assert c.post('/api/v1/approval/admin/flows/12/nodes', json={'node_code': 'n1', 'node_name': '一级审批', 'node_mode': 'or'}).json()['data']['id'] == 15
            assert c.get('/api/v1/approval/admin/exceptions').json()['data'][0]['id'] == 88
            assert c.post('/api/v1/approval/admin/exceptions/88/retry', json={'action': 'retry'}).json()['data']['status'] == 'resolved'
            assert c.post('/api/v1/approval/admin/exceptions/88/retry', json={'action': 'assign_approvers', 'approver_user_ids': [101, 102]}).json()['data']['status'] == 'resolved'
            assert c.post('/api/v1/approval/admin/exceptions/88/retry', json={'action': 'skip_node'}).json()['data']['status'] == 'resolved'
    assert mock_retry_exception.await_args_list[1].kwargs['approver_user_ids'] == [101, 102]

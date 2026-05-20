from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import ApprovalRouteRule, ApprovalScenario
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_scenario_admin_service import ApprovalScenarioAdminService


@dataclass
class _User:
    user_id: int
    admin: bool = False

    def is_admin(self) -> bool:
        return self.admin


class FakeApprovalRepo:
    def __init__(self) -> None:
        self.instances: dict[int, ApprovalInstance] = {}
        self.tasks: dict[int, ApprovalTask] = {}
        self.action_logs: list[ApprovalActionLog] = []

    async def get_instance(self, instance_id: int) -> ApprovalInstance | None:
        return self.instances.get(instance_id)

    async def update_instance(self, instance: ApprovalInstance) -> ApprovalInstance:
        self.instances[instance.id] = instance
        return instance

    async def get_task(self, task_id: int) -> ApprovalTask | None:
        return self.tasks.get(task_id)

    async def update_task(self, task: ApprovalTask) -> ApprovalTask:
        self.tasks[task.id] = task
        return task

    async def list_tasks(self, instance_id: int) -> list[ApprovalTask]:
        return [task for task in self.tasks.values() if task.instance_id == instance_id]

    async def create_action_log(self, row: ApprovalActionLog) -> ApprovalActionLog:
        row.id = len(self.action_logs) + 1
        self.action_logs.append(row)
        return row


def _build_instance(status: str = ApprovalInstanceStatus.PENDING) -> ApprovalInstance:
    return ApprovalInstance(
        id=1,
        tenant_id=1,
        scenario_code='menu_access_request',
        scenario_name='菜单权限申请',
        handler_key='menu_access_request',
        business_key='menu:knowledge:user:7',
        business_resource_type='web_menu',
        business_resource_id='knowledge',
        business_name='知识库',
        applicant_user_id=7,
        applicant_user_name='alice',
        status=status,
        payload_snapshot={'menu_key': 'knowledge'},
        detail_snapshot={'menu_name': '知识库'},
        current_node_name='一级审批',
    )


def _build_task(
    task_id: int,
    *,
    node_order: int,
    approver_user_id: int,
    status: str = ApprovalTaskStatus.PENDING,
) -> ApprovalTask:
    return ApprovalTask(
        id=task_id,
        tenant_id=1,
        instance_id=1,
        flow_version_id=1,
        node_code=f'n{node_order}',
        node_name=f'第{node_order}级审批',
        node_order=node_order,
        approver_user_id=approver_user_id,
        approver_source_type='user',
        node_mode='or',
        status=status,
    )


@pytest.mark.asyncio
async def test_list_my_tasks_aggregates_instance_summary(monkeypatch: pytest.MonkeyPatch):
    task = _build_task(11, node_order=1, approver_user_id=9)
    instance = _build_instance()
    monkeypatch.setattr(
        ApprovalQueryRepository,
        'list_tasks_by_approver',
        AsyncMock(return_value=[task]),
    )
    monkeypatch.setattr(
        ApprovalInstanceRepository,
        'get_instance',
        AsyncMock(return_value=instance),
    )

    result = await ApprovalCenterService.list_my_tasks(tenant_id=1, approver_user_id=9)

    assert result['total'] == 1
    assert result['data'][0]['task_id'] == 11
    assert result['data'][0]['scenario_code'] == 'menu_access_request'
    assert result['data'][0]['business_name'] == '知识库'


@pytest.mark.asyncio
async def test_get_instance_detail_blocks_unrelated_user_and_returns_action_logs(monkeypatch: pytest.MonkeyPatch):
    instance = _build_instance()
    task = _build_task(11, node_order=1, approver_user_id=9)
    action_log = ApprovalActionLog(
        id=1,
        tenant_id=1,
        instance_id=1,
        action='approved',
        operator_user_id=9,
        operator_user_name='reviewer',
        detail={'comment': 'ok'},
        create_time=datetime.utcnow(),
    )
    monkeypatch.setattr(ApprovalInstanceRepository, 'get_instance', AsyncMock(return_value=instance))
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_tasks', AsyncMock(return_value=[task]))
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_action_logs', AsyncMock(return_value=[action_log]))

    with pytest.raises(PermissionError):
        await ApprovalCenterService.get_instance_detail(instance_id=1, login_user=_User(user_id=88))

    detail = await ApprovalCenterService.get_instance_detail(instance_id=1, login_user=_User(user_id=9))
    assert detail['instance_id'] == 1
    assert detail['tasks'][0]['task_id'] == 11
    assert detail['action_logs'][0]['action'] == 'approved'


@pytest.mark.asyncio
async def test_withdraw_instance_cancels_pending_tasks_and_records_log(monkeypatch: pytest.MonkeyPatch):
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance()
    repo.tasks[1] = _build_task(1, node_order=1, approver_user_id=9)
    repo.tasks[2] = _build_task(2, node_order=2, approver_user_id=10, status=ApprovalTaskStatus.APPROVED)
    audit_log = AsyncMock()
    monkeypatch.setattr(ApprovalInstanceRepository, 'get_instance', repo.get_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, 'update_instance', repo.update_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_tasks', repo.list_tasks)
    monkeypatch.setattr(ApprovalInstanceRepository, 'update_task', repo.update_task)
    monkeypatch.setattr(ApprovalInstanceRepository, 'create_action_log', repo.create_action_log)
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_action_logs', AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalCenterService, '_write_audit_log', audit_log)

    result = await ApprovalCenterService.withdraw_instance(
        instance_id=1,
        operator_user_id=7,
        operator_user_name='alice',
        reason='cancel request',
    )

    assert repo.instances[1].status == ApprovalInstanceStatus.WITHDRAWN
    assert repo.tasks[1].status == ApprovalTaskStatus.CANCELLED
    assert repo.tasks[1].comment == 'cancel request'
    assert repo.tasks[2].status == ApprovalTaskStatus.APPROVED
    assert repo.action_logs[-1].action == 'withdrawn'
    assert result['status'] == ApprovalInstanceStatus.WITHDRAWN
    audit_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_resubmit_instance_reopens_first_node_and_cancels_later_nodes(monkeypatch: pytest.MonkeyPatch):
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.REJECTED)
    repo.tasks[1] = _build_task(1, node_order=1, approver_user_id=9, status=ApprovalTaskStatus.REJECTED)
    repo.tasks[2] = _build_task(2, node_order=2, approver_user_id=10, status=ApprovalTaskStatus.PENDING)
    monkeypatch.setattr(ApprovalInstanceRepository, 'get_instance', repo.get_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, 'update_instance', repo.update_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_tasks', repo.list_tasks)
    monkeypatch.setattr(ApprovalInstanceRepository, 'update_task', repo.update_task)
    monkeypatch.setattr(ApprovalInstanceRepository, 'create_action_log', repo.create_action_log)
    monkeypatch.setattr(ApprovalInstanceRepository, 'list_action_logs', AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalCenterService, '_write_audit_log', AsyncMock())

    result = await ApprovalCenterService.resubmit_instance(
        instance_id=1,
        operator_user_id=7,
        operator_user_name='alice',
        reason='updated reason',
    )

    assert repo.instances[1].status == ApprovalInstanceStatus.PENDING
    assert repo.tasks[1].status == ApprovalTaskStatus.PENDING
    assert repo.tasks[1].comment is None
    assert repo.tasks[2].status == ApprovalTaskStatus.CANCELLED
    assert repo.action_logs[-1].action == 'resubmitted'
    assert result['status'] == ApprovalInstanceStatus.PENDING


@pytest.mark.asyncio
async def test_admin_service_lists_and_creates_scenarios(monkeypatch: pytest.MonkeyPatch):
    scenario = ApprovalScenario(
        id=1,
        tenant_id=1,
        scenario_code='menu_access_request',
        scenario_name='菜单权限申请',
        enabled=True,
    )
    route = ApprovalRouteRule(
        id=2,
        tenant_id=1,
        scenario_id=1,
        route_name='默认流程',
        route_type='flow',
        sort_order=1,
        flow_definition_id=3,
        match_config={},
    )
    exception = ApprovalException(
        id=8,
        tenant_id=1,
        instance_id=1,
        exception_type='route_missing',
        status='open',
        detail={},
    )

    monkeypatch.setattr(ApprovalScenarioRepository, 'list_scenarios', AsyncMock(return_value=[scenario]))
    monkeypatch.setattr(ApprovalScenarioRepository, 'get_scenario_by_code', AsyncMock(return_value=scenario))
    monkeypatch.setattr(ApprovalScenarioRepository, 'create_scenario', AsyncMock(return_value=scenario))
    monkeypatch.setattr(ApprovalScenarioRepository, 'list_route_rules', AsyncMock(return_value=[route]))
    monkeypatch.setattr(ApprovalQueryRepository, 'list_open_exceptions', AsyncMock(return_value=[exception]))
    monkeypatch.setattr(
        'bisheng.approval.domain.services.approval_scenario_admin_service.AuditLogDao.ainsert_v2',
        AsyncMock(),
    )

    scenarios = await ApprovalScenarioAdminService.list_scenarios(tenant_id=1)
    created = await ApprovalScenarioAdminService.create_scenario(
        tenant_id=1,
        payload={'scenario_code': 'menu_access_request', 'scenario_name': '菜单权限申请', 'enabled': True},
        operator_user_id=1,
        operator_user_name='admin',
    )
    routes = await ApprovalScenarioAdminService.list_routes(tenant_id=1, scenario_id=1)
    exceptions = await ApprovalScenarioAdminService.list_open_exceptions(tenant_id=1)

    assert scenarios[0]['scenario_code'] == 'menu_access_request'
    assert created['id'] == 1
    assert routes[0]['route_type'] == 'flow'
    assert exceptions[0]['exception_type'] == 'route_missing'

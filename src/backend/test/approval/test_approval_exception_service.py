from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService


@dataclass
class _FlowNode:
    node_code: str
    node_name: str
    node_order: int
    node_mode: str


class FakeApprovalRepo:
    def __init__(self) -> None:
        self.instances: dict[int, ApprovalInstance] = {}
        self.tasks: dict[int, ApprovalTask] = {}
        self.exceptions: dict[int, ApprovalException] = {}
        self.outboxes: dict[int, ApprovalOutbox] = {}
        self.action_logs: list[dict] = []
        self.outbox_payloads: list[dict] = []
        self._task_id = 100

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

    async def create_task(self, task: ApprovalTask) -> ApprovalTask:
        self._task_id += 1
        task.id = self._task_id
        self.tasks[task.id] = task
        return task

    async def get_exception(self, exception_id: int) -> ApprovalException | None:
        return self.exceptions.get(exception_id)

    async def update_exception(self, exception: ApprovalException) -> ApprovalException:
        self.exceptions[exception.id] = exception
        return exception

    async def create_action_log(self, payload: dict) -> None:
        self.action_logs.append(payload)

    async def create_outbox(self, payload: ApprovalOutbox) -> None:
        self.outbox_payloads.append(payload)

    async def list_outbox(self, instance_id: int) -> list[ApprovalOutbox]:
        return [outbox for outbox in self.outboxes.values() if outbox.instance_id == instance_id]

    async def update_outbox(self, outbox: ApprovalOutbox) -> ApprovalOutbox:
        self.outboxes[outbox.id] = outbox
        return outbox


def _build_instance(status: str = ApprovalInstanceStatus.PENDING) -> ApprovalInstance:
    return ApprovalInstance(
        id=1,
        tenant_id=1,
        scenario_code='knowledge_space_subscribe_request',
        scenario_name='知识空间加入审批',
        handler_key='knowledge_space_subscribe_request',
        business_key='space:12:user:7',
        business_resource_type='knowledge_space',
        business_resource_id='12',
        business_name='研发知识空间',
        applicant_user_id=7,
        applicant_user_name='alice',
        flow_version_id=1,
        route_rule_id=1,
        status=status,
        payload_snapshot={'space_id': 12},
        detail_snapshot={'space_name': '研发知识空间'},
        current_node_name='一级审批',
    )


def _build_task(task_id: int, *, user_id: int, node_mode: str = 'or', status: str = ApprovalTaskStatus.PENDING) -> ApprovalTask:
    return ApprovalTask(
        id=task_id,
        tenant_id=1,
        instance_id=1,
        flow_version_id=1,
        node_code='n1',
        node_name='一级审批',
        node_order=1,
        approver_user_id=user_id,
        approver_source_type='user',
        node_mode=node_mode,
        status=status,
    )


@pytest.mark.asyncio
async def test_or_sign_approves_one_and_skips_other_tasks(monkeypatch: pytest.MonkeyPatch):
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance()
    repo.tasks[1] = _build_task(1, user_id=1001, node_mode='or')
    repo.tasks[2] = _build_task(2, user_id=1002, node_mode='or')
    service = ApprovalCenterService(instance_repository=repo)
    monkeypatch.setattr(ApprovalCenterService, '_write_audit_log', AsyncMock())

    await service.decide_task(task_id=1, action='approve', operator_user_id=1001, operator_user_name='u1')

    assert repo.tasks[1].status == ApprovalTaskStatus.APPROVED
    assert repo.tasks[2].status == ApprovalTaskStatus.SKIPPED
    assert repo.instances[1].status == ApprovalInstanceStatus.APPROVED
    assert len(repo.outbox_payloads) == 1
    assert repo.outbox_payloads[0].instance_id == 1
    assert repo.outbox_payloads[0].handler_key == 'knowledge_space_subscribe_request'


@pytest.mark.asyncio
async def test_countersign_requires_all_tasks_to_approve(monkeypatch: pytest.MonkeyPatch):
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance()
    repo.tasks[1] = _build_task(1, user_id=1001, node_mode='and')
    repo.tasks[2] = _build_task(2, user_id=1002, node_mode='and')
    service = ApprovalCenterService(instance_repository=repo)
    monkeypatch.setattr(ApprovalCenterService, '_write_audit_log', AsyncMock())

    await service.decide_task(task_id=1, action='approve', operator_user_id=1001, operator_user_name='u1')
    assert repo.instances[1].status == ApprovalInstanceStatus.PENDING

    await service.decide_task(task_id=2, action='approve', operator_user_id=1002, operator_user_name='u2')
    assert repo.instances[1].status == ApprovalInstanceStatus.APPROVED


@pytest.mark.asyncio
async def test_reject_terminates_instance_and_cancels_siblings(monkeypatch: pytest.MonkeyPatch):
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance()
    repo.tasks[1] = _build_task(1, user_id=1001)
    repo.tasks[2] = _build_task(2, user_id=1002)
    service = ApprovalCenterService(instance_repository=repo)
    monkeypatch.setattr(ApprovalCenterService, '_write_audit_log', AsyncMock())

    await service.decide_task(task_id=1, action='reject', operator_user_id=1001, operator_user_name='u1', comment='reject')

    assert repo.tasks[1].status == ApprovalTaskStatus.REJECTED
    assert repo.tasks[2].status == ApprovalTaskStatus.CANCELLED
    assert repo.instances[1].status == ApprovalInstanceStatus.REJECTED


@pytest.mark.asyncio
async def test_scenario_disabled_retry_reopens_instance_and_creates_task():
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.EXCEPTION)
    repo.exceptions[1] = ApprovalException(
        id=1,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.SCENARIO_DISABLED,
        status='open',
        detail={},
    )
    service = ApprovalExceptionService(instance_repository=repo)

    await service.retry_scenario_disabled(
        exception_id=1,
        flow_version_id=2,
        route_rule_id=9,
        node=_FlowNode(node_code='n2', node_name='二级审批', node_order=2, node_mode='or'),
        approver_user_ids=[2001],
        resolved_by_user_id=1,
    )

    assert repo.instances[1].status == ApprovalInstanceStatus.PENDING
    assert repo.instances[1].flow_version_id == 2
    assert repo.exceptions[1].status == 'resolved'
    created_task = next(task for task in repo.tasks.values() if task.node_code == 'n2')
    assert created_task.approver_user_id == 2001
    assert any(isinstance(log, ApprovalActionLog) and log.action == 'retry_scenario_disabled' for log in repo.action_logs)


@pytest.mark.asyncio
async def test_route_missing_assign_flow_continues_instance():
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.EXCEPTION)
    repo.exceptions[1] = ApprovalException(
        id=1,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.ROUTE_MISSING,
        status='open',
        detail={},
    )
    service = ApprovalExceptionService(instance_repository=repo)

    await service.assign_flow(
        exception_id=1,
        flow_version_id=3,
        route_rule_id=10,
        node=_FlowNode(node_code='n3', node_name='三级审批', node_order=3, node_mode='and'),
        approver_user_ids=[3001, 3002],
        resolved_by_user_id=1,
    )

    assert repo.instances[1].status == ApprovalInstanceStatus.PENDING
    assert repo.instances[1].flow_version_id == 3
    assert len([task for task in repo.tasks.values() if task.node_code == 'n3']) == 2


@pytest.mark.asyncio
async def test_approver_empty_can_assign_approver_or_skip_node():
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.EXCEPTION)
    repo.exceptions[1] = ApprovalException(
        id=1,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.APPROVER_EMPTY,
        status='open',
        detail={'node_code': 'n1', 'node_name': '一级审批', 'node_order': 1, 'node_mode': 'or'},
    )
    service = ApprovalExceptionService(instance_repository=repo)

    await service.assign_approvers(exception_id=1, approver_user_ids=[4001], resolved_by_user_id=1)
    assert any(task.approver_user_id == 4001 for task in repo.tasks.values())

    repo.exceptions[2] = ApprovalException(
        id=2,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.APPROVER_EMPTY,
        status='open',
        detail={'node_code': 'n1', 'node_name': '一级审批', 'node_order': 1, 'node_mode': 'or'},
    )
    await service.skip_node(exception_id=2, resolved_by_user_id=1)
    assert repo.exceptions[2].status == 'resolved'


@pytest.mark.asyncio
async def test_execute_failed_retry_success_and_failure():
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.EXECUTE_FAILED)
    repo.exceptions[1] = ApprovalException(
        id=1,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
        status='open',
        detail={},
    )
    service = ApprovalExceptionService(instance_repository=repo)

    await service.retry_execute_failed(exception_id=1, resolved_by_user_id=1, executor=lambda instance_id: True)
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTED
    assert repo.exceptions[1].status == 'resolved'

    repo.instances[2] = _build_instance(status=ApprovalInstanceStatus.EXECUTE_FAILED)
    repo.instances[2].id = 2
    repo.exceptions[2] = ApprovalException(
        id=2,
        tenant_id=1,
        instance_id=2,
        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
        status='open',
        detail={},
    )
    await service.retry_execute_failed(exception_id=2, resolved_by_user_id=1, executor=lambda instance_id: False)
    assert repo.instances[2].status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert repo.exceptions[2].status == 'open'


@pytest.mark.asyncio
async def test_retry_execute_failed_api_marks_outbox_success_or_failure():
    repo = FakeApprovalRepo()
    repo.instances[1] = _build_instance(status=ApprovalInstanceStatus.EXECUTE_FAILED)
    repo.exceptions[1] = ApprovalException(
        id=1,
        tenant_id=1,
        instance_id=1,
        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
        status='open',
        detail={},
    )
    repo.outboxes[1] = ApprovalOutbox(
        id=1,
        tenant_id=1,
        instance_id=1,
        handler_key='knowledge_space_subscribe_request',
        status=ApprovalOutboxStatus.FAILED,
        payload_snapshot={'space_id': 12, 'applicant_user_id': 7},
    )
    service = ApprovalExceptionService(instance_repository=repo)
    service._write_audit_log = AsyncMock()  # type: ignore[method-assign]

    class _SuccessHandler:
        async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
            return {'instance_id': instance_id, 'payload': payload_snapshot}

    async def _build_success_handler(_scenario_code: str):
        return _SuccessHandler()

    service._build_handler = _build_success_handler  # type: ignore[method-assign]
    success = await service.retry_execute_failed_api(
        exception_id=1,
        resolved_by_user_id=1,
        scenario_code='knowledge_space_subscribe_request',
    )

    assert success is True
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTED
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS
    assert repo.exceptions[1].status == 'resolved'

    repo.instances[2] = _build_instance(status=ApprovalInstanceStatus.EXECUTE_FAILED)
    repo.instances[2].id = 2
    repo.exceptions[2] = ApprovalException(
        id=2,
        tenant_id=1,
        instance_id=2,
        exception_type=ApprovalExceptionType.EXECUTE_FAILED,
        status='open',
        detail={},
    )
    repo.outboxes[2] = ApprovalOutbox(
        id=2,
        tenant_id=1,
        instance_id=2,
        handler_key='knowledge_space_subscribe_request',
        status=ApprovalOutboxStatus.FAILED,
        payload_snapshot={'space_id': 12, 'applicant_user_id': 7},
    )

    class _FailHandler:
        async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
            raise RuntimeError('retry failed')

    async def _build_fail_handler(_scenario_code: str):
        return _FailHandler()

    service._build_handler = _build_fail_handler  # type: ignore[method-assign]
    success = await service.retry_execute_failed_api(
        exception_id=2,
        resolved_by_user_id=1,
        scenario_code='knowledge_space_subscribe_request',
    )

    assert success is False
    assert repo.instances[2].status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert repo.outboxes[2].status == ApprovalOutboxStatus.FAILED
    assert repo.outboxes[2].error_summary == 'retry failed'
    assert repo.exceptions[2].status == 'open'

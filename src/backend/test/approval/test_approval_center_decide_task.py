"""Tests for ApprovalCenterService.decide_task multi-node flow advancement.

Covers the bug where approving an intermediate node (OR or AND mode) was
incorrectly finalizing the entire approval instance instead of advancing to
the next node.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalException.__table__,
        ApprovalOutbox.__table__,
        ApprovalActionLog.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def repos(db_engine, monkeypatch):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=db_engine) as session:
            yield session

    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session',
        _factory,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_three_node_flow() -> tuple[ApprovalFlowVersion, list[ApprovalNodeDefinition]]:
    """Create a 3-node flow: OR → AND → OR (orders 1, 2, 3)."""
    fd = await ApprovalScenarioRepository.create_flow_definition(
        ApprovalFlowDefinition(
            tenant_id=1,
            scenario_id=0,
            flow_code='test_flow',
            flow_name='测试三节点流程',
            is_active=True,
        )
    )
    fv = await ApprovalScenarioRepository.create_flow_version(
        ApprovalFlowVersion(
            tenant_id=1,
            flow_definition_id=fd.id,
            version_no=1,
            is_active=True,
            definition_snapshot={},
        )
    )
    node1 = await ApprovalScenarioRepository.create_node_definition(
        ApprovalNodeDefinition(
            tenant_id=1, flow_version_id=fv.id,
            node_code='node_or1', node_name='或', node_order=1, node_mode='or',
            approver_config={'sources': [{'type': 'direct_user', 'user_ids': [101, 102]}]},
            extra_config={},
        )
    )
    node2 = await ApprovalScenarioRepository.create_node_definition(
        ApprovalNodeDefinition(
            tenant_id=1, flow_version_id=fv.id,
            node_code='node_and', node_name='A', node_order=2, node_mode='and',
            approver_config={'sources': [{'type': 'direct_user', 'user_ids': [201]}]},
            extra_config={},
        )
    )
    node3 = await ApprovalScenarioRepository.create_node_definition(
        ApprovalNodeDefinition(
            tenant_id=1, flow_version_id=fv.id,
            node_code='node_or2', node_name='或2', node_order=3, node_mode='or',
            approver_config={'sources': [{'type': 'direct_user', 'user_ids': [301]}]},
            extra_config={},
        )
    )
    return fv, [node1, node2, node3]


async def _make_instance(fv: ApprovalFlowVersion, node_name: str) -> ApprovalInstance:
    return await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code='menu_access_request',
            scenario_name='菜单权限申请',
            handler_key='menu_access_request',
            business_key='menu:home:user:5',
            business_resource_type='web_menu',
            business_resource_id='home',
            business_name='首页',
            applicant_user_id=5,
            applicant_user_name='tester',
            flow_version_id=fv.id,
            status=ApprovalInstanceStatus.PENDING,
            current_node_name=node_name,
            payload_snapshot={'menu_key': 'home'},
            detail_snapshot={},
        )
    )


async def _make_task(instance: ApprovalInstance, node: ApprovalNodeDefinition, approver_id: int) -> ApprovalTask:
    return await ApprovalInstanceRepository.create_task(
        ApprovalTask(
            tenant_id=1,
            instance_id=instance.id,
            flow_version_id=instance.flow_version_id,
            node_code=node.node_code,
            node_name=node.node_name,
            node_order=node.node_order,
            approver_user_id=approver_id,
            approver_source_type='resolved',
            node_mode=node.node_mode,
            status=ApprovalTaskStatus.PENDING,
        )
    )


from contextlib import contextmanager


@contextmanager
def _service_infra_mocked():
    """Suppress all side effects that touch real DB / messaging infrastructure."""
    with patch.object(ApprovalCenterService, '_dispatch_outbox', return_value=None), \
         patch.object(ApprovalCenterService, '_write_audit_log', new=AsyncMock(return_value=None)), \
         patch.object(ApprovalCenterService, '_send_approval_notify', new=AsyncMock(return_value=None)):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_or_node_approval_advances_to_next_node_not_finalize(repos):
    """OR node: one approval must create tasks for the next node, NOT finalize."""
    fv, (node1, node2, node3) = await _seed_three_node_flow()
    instance = await _make_instance(fv, node1.node_name)
    task101 = await _make_task(instance, node1, 101)
    await _make_task(instance, node1, 102)

    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)

    with _service_infra_mocked():
        await service.decide_task(
            task_id=task101.id,
            action='approve',
            operator_user_id=101,
            operator_user_name='user101',
            operator_tenant_id=1,
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    all_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)

    # Instance must still be PENDING — not finalized yet
    assert refreshed.status == ApprovalInstanceStatus.PENDING
    # current_node_name must have advanced to node 2
    assert refreshed.current_node_name == node2.node_name
    # New task created for node 2 approver (201)
    node2_tasks = [t for t in all_tasks if t.node_code == node2.node_code]
    assert len(node2_tasks) == 1
    assert node2_tasks[0].approver_user_id == 201
    assert node2_tasks[0].status == ApprovalTaskStatus.PENDING
    # Node 1 sibling must be SKIPPED
    node1_tasks = [t for t in all_tasks if t.node_code == node1.node_code]
    statuses = {t.approver_user_id: t.status for t in node1_tasks}
    assert statuses[101] == ApprovalTaskStatus.APPROVED
    assert statuses[102] == ApprovalTaskStatus.SKIPPED


@pytest.mark.asyncio
async def test_and_node_partial_approval_does_not_advance(repos):
    """AND node: approving only some tasks must NOT advance or finalize."""
    fv, (node1, node2, node3) = await _seed_three_node_flow()
    instance = await _make_instance(fv, node2.node_name)
    task201 = await _make_task(instance, node2, 201)
    task202 = await _make_task(instance, node2, 202)

    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
    with _service_infra_mocked():
        await service.decide_task(
            task_id=task201.id,
            action='approve',
            operator_user_id=201,
            operator_user_name='user201',
            operator_tenant_id=1,
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    all_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)

    assert refreshed.status == ApprovalInstanceStatus.PENDING
    # No node3 tasks created yet
    node3_tasks = [t for t in all_tasks if t.node_code == node3.node_code]
    assert node3_tasks == []
    # task202 must still be pending
    updated_202 = next(t for t in all_tasks if t.approver_user_id == 202)
    assert updated_202.status == ApprovalTaskStatus.PENDING


@pytest.mark.asyncio
async def test_and_node_full_approval_advances_to_next_node(repos):
    """AND node: all approvals done must advance to next node, not finalize."""
    fv, (node1, node2, node3) = await _seed_three_node_flow()
    instance = await _make_instance(fv, node2.node_name)
    task201 = await _make_task(instance, node2, 201)

    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
    with _service_infra_mocked():
        await service.decide_task(
            task_id=task201.id,
            action='approve',
            operator_user_id=201,
            operator_user_name='user201',
            operator_tenant_id=1,
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    all_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)

    assert refreshed.status == ApprovalInstanceStatus.PENDING
    assert refreshed.current_node_name == node3.node_name
    node3_tasks = [t for t in all_tasks if t.node_code == node3.node_code]
    assert len(node3_tasks) == 1
    assert node3_tasks[0].approver_user_id == 301


@pytest.mark.asyncio
async def test_last_node_approval_finalizes_instance(repos):
    """Approving the last node must mark the instance APPROVED and create outbox."""
    fv, (node1, node2, node3) = await _seed_three_node_flow()
    instance = await _make_instance(fv, node3.node_name)
    task301 = await _make_task(instance, node3, 301)

    dispatched: list[int] = []

    with _service_infra_mocked(), \
         patch.object(ApprovalCenterService, '_dispatch_outbox', side_effect=lambda oid: dispatched.append(oid)):
        service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
        await service.decide_task(
            task_id=task301.id,
            action='approve',
            operator_user_id=301,
            operator_user_name='user301',
            operator_tenant_id=1,
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    outboxes = await ApprovalInstanceRepository.list_outbox(instance.id)

    assert refreshed.status == ApprovalInstanceStatus.APPROVED
    assert refreshed.current_node_name is None
    assert len(outboxes) == 1
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_rejection_at_intermediate_node_terminates_instance(repos):
    """Rejection at any node must mark instance REJECTED without advancing."""
    fv, (node1, node2, node3) = await _seed_three_node_flow()
    instance = await _make_instance(fv, node1.node_name)
    task101 = await _make_task(instance, node1, 101)
    await _make_task(instance, node1, 102)

    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
    with _service_infra_mocked():
        await service.decide_task(
            task_id=task101.id,
            action='reject',
            operator_user_id=101,
            operator_user_name='user101',
            operator_tenant_id=1,
            comment='not approved',
        )

    refreshed = await ApprovalInstanceRepository.get_instance(instance.id)
    all_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)

    assert refreshed.status == ApprovalInstanceStatus.REJECTED
    node2_tasks = [t for t in all_tasks if t.node_code == node2.node_code]
    assert node2_tasks == []

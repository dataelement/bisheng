from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

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
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository


@pytest_asyncio.fixture
async def approval_runtime_engine():
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
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_runtime_repositories(approval_runtime_engine, monkeypatch):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=approval_runtime_engine) as session:
            yield session

    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session',
        _factory,
    )
    yield


async def _seed_flow() -> tuple[ApprovalScenario, ApprovalRouteRule, ApprovalFlowVersion, ApprovalNodeDefinition]:
    scenario = await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=1,
            scenario_code='knowledge_space_subscribe_request',
            scenario_name='知识空间加入审批',
            enabled=True,
        )
    )
    flow_definition = await ApprovalScenarioRepository.create_flow_definition(
        ApprovalFlowDefinition(
            tenant_id=1,
            scenario_id=scenario.id,
            flow_code='knowledge_space_flow',
            flow_name='知识空间审批流',
            is_active=True,
        )
    )
    flow_version = await ApprovalScenarioRepository.create_flow_version(
        ApprovalFlowVersion(
            tenant_id=1,
            flow_definition_id=flow_definition.id,
            version_no=1,
            is_active=True,
            definition_snapshot={'version': 1},
        )
    )
    route_rule = await ApprovalScenarioRepository.create_route_rule(
        ApprovalRouteRule(
            tenant_id=1,
            scenario_id=scenario.id,
            route_name='default approval route',
            route_type='flow',
            sort_order=1,
            flow_definition_id=flow_definition.id,
            match_config={'all': True},
        )
    )
    node = await ApprovalScenarioRepository.create_node_definition(
        ApprovalNodeDefinition(
            tenant_id=1,
            flow_version_id=flow_version.id,
            node_code='first_node',
            node_name='一级审批',
            node_order=1,
            node_mode='or',
            approver_config={'type': 'direct'},
            extra_config={},
        )
    )
    return scenario, route_rule, flow_version, node


@pytest.mark.asyncio
async def test_repository_flow_creates_pass_instance_without_task(patched_runtime_repositories):
    scenario = await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            scenario_name='频道订阅审批',
            enabled=True,
        )
    )
    await ApprovalScenarioRepository.create_route_rule(
        ApprovalRouteRule(
            tenant_id=1,
            scenario_id=scenario.id,
            route_name='direct pass',
            route_type='pass',
            sort_order=1,
            match_config={'department': 'all'},
        )
    )

    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='channel_subscribe',
            business_key='channel:99:user:7',
            business_resource_type='channel',
            business_resource_id='99',
            business_name='产品动态',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.EXECUTED,
            payload_snapshot={'channel_id': 99},
            detail_snapshot={'channel_name': '产品动态'},
        )
    )

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    outbox = await ApprovalInstanceRepository.list_outbox(instance.id)
    my_requests = await ApprovalQueryRepository.list_instances_by_applicant(1, 7)

    assert instance.status == ApprovalInstanceStatus.EXECUTED
    assert tasks == []
    assert outbox == []
    assert [one.id for one in my_requests] == [instance.id]


@pytest.mark.asyncio
async def test_repository_flow_creates_pending_instance_and_first_task(patched_runtime_repositories):
    scenario, route_rule, flow_version, node = await _seed_flow()

    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='knowledge_space_subscribe',
            business_key='space:12:user:7',
            business_resource_type='knowledge_space',
            business_resource_id='12',
            business_name='研发知识空间',
            applicant_user_id=7,
            applicant_user_name='alice',
            flow_version_id=flow_version.id,
            route_rule_id=route_rule.id,
            current_node_name=node.node_name,
            status=ApprovalInstanceStatus.PENDING,
            payload_snapshot={'space_id': 12},
            detail_snapshot={'space_name': '研发知识空间'},
        )
    )
    task = await ApprovalInstanceRepository.create_task(
        ApprovalTask(
            tenant_id=1,
            instance_id=instance.id,
            flow_version_id=flow_version.id,
            node_code=node.node_code,
            node_name=node.node_name,
            node_order=node.node_order,
            approver_user_id=1001,
            approver_source_type='user',
            node_mode=node.node_mode,
            status=ApprovalTaskStatus.PENDING,
        )
    )

    tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
    approver_tasks = await ApprovalQueryRepository.list_tasks_by_approver(1, 1001)
    node_defs = await ApprovalScenarioRepository.list_node_definitions(1, flow_version.id)

    assert instance.status == ApprovalInstanceStatus.PENDING
    assert task.status == ApprovalTaskStatus.PENDING
    assert [one.node_code for one in tasks] == ['first_node']
    assert [one.id for one in approver_tasks] == [task.id]
    assert [one.node_name for one in node_defs] == ['一级审批']


@pytest.mark.asyncio
async def test_repository_flow_creates_outbox_after_final_approval(patched_runtime_repositories):
    scenario = await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=2,
            scenario_code='menu_access_request',
            scenario_name='菜单权限申请',
            enabled=True,
        )
    )
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=2,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='menu_access',
            business_key='menu:model:user:18',
            business_resource_type='web_menu',
            business_resource_id='model',
            business_name='模型管理',
            applicant_user_id=18,
            applicant_user_name='bob',
            status=ApprovalInstanceStatus.APPROVED,
            payload_snapshot={'menu_key': 'model'},
            detail_snapshot={'menu_name': '模型管理'},
        )
    )
    outbox = await ApprovalInstanceRepository.create_outbox(
        ApprovalOutbox(
            tenant_id=2,
            instance_id=instance.id,
            handler_key='menu_access',
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot={'menu_key': 'model'},
        )
    )

    saved_outbox = await ApprovalInstanceRepository.list_outbox(instance.id)
    tenant_one_requests = await ApprovalQueryRepository.list_instances_by_applicant(1, 18)
    tenant_two_requests = await ApprovalQueryRepository.list_instances_by_applicant(2, 18)

    assert outbox.status == ApprovalOutboxStatus.PENDING
    assert [one.id for one in saved_outbox] == [outbox.id]
    assert tenant_one_requests == []
    assert [one.id for one in tenant_two_requests] == [instance.id]


@pytest.mark.asyncio
async def test_repository_flow_lists_routes_logs_and_open_exceptions(patched_runtime_repositories):
    scenario, route_rule, flow_version, node = await _seed_flow()
    await ApprovalScenarioRepository.create_route_rule(
        ApprovalRouteRule(
            tenant_id=1,
            scenario_id=scenario.id,
            route_name='fallback route',
            route_type='flow',
            sort_order=2,
            flow_definition_id=route_rule.flow_definition_id,
            match_config={'fallback': True},
        )
    )
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='knowledge_space_subscribe',
            business_key='space:18:user:9',
            business_resource_type='knowledge_space',
            business_resource_id='18',
            business_name='产品知识空间',
            applicant_user_id=9,
            applicant_user_name='bob',
            flow_version_id=flow_version.id,
            route_rule_id=route_rule.id,
            current_node_name=node.node_name,
            status=ApprovalInstanceStatus.EXCEPTION,
            payload_snapshot={'space_id': 18},
            detail_snapshot={'space_name': '产品知识空间'},
        )
    )
    await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=1,
            instance_id=instance.id,
            exception_type=ApprovalExceptionType.APPROVER_EMPTY,
            detail={'node_code': node.node_code},
        )
    )
    await ApprovalInstanceRepository.create_action_log(
        ApprovalActionLog(
            tenant_id=1,
            instance_id=instance.id,
            action='instance_created',
            operator_user_id=9,
            operator_user_name='bob',
            detail={'status': ApprovalInstanceStatus.EXCEPTION},
        )
    )

    routes = await ApprovalScenarioRepository.list_route_rules(1, scenario.id)
    active_version = await ApprovalScenarioRepository.get_active_flow_version(1, route_rule.flow_definition_id)
    logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
    open_exceptions = await ApprovalQueryRepository.list_open_exceptions(1)

    assert [one.sort_order for one in routes] == [1, 2]
    assert active_version is not None
    assert active_version.id == flow_version.id
    assert [one.action for one in logs] == ['instance_created']
    assert [one.instance_id for one in open_exceptions] == [instance.id]

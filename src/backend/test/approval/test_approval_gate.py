from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
)
from bisheng.approval.domain.models.approval_scenario import ApprovalScenario
from bisheng.approval.domain.models.user_menu_access import UserMenuAccess, UserMenuAccessStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry


@pytest_asyncio.fixture
async def approval_db_engine():
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalScenario.__table__,
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalException.__table__,
        UserMenuAccess.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_approval_repositories(approval_db_engine, monkeypatch):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=approval_db_engine) as session:
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
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.user_menu_access_repository.get_async_db_session',
        _factory,
    )
    yield


@pytest.mark.asyncio
async def test_repository_flow_creates_scenario_disabled_exception(patched_approval_repositories):
    scenario = await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=1,
            scenario_code='menu_access_request',
            scenario_name='菜单权限申请',
            enabled=False,
        )
    )
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='menu_access',
            business_key='menu:knowledge',
            business_resource_type='web_menu',
            business_resource_id='knowledge',
            business_name='知识管理',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.EXCEPTION,
            payload_snapshot={'menu_key': 'knowledge'},
            detail_snapshot={'menu_name': '知识管理'},
        )
    )
    await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=1,
            instance_id=instance.id,
            exception_type=ApprovalExceptionType.SCENARIO_DISABLED,
            detail={'scenario_code': scenario.scenario_code},
        )
    )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    exceptions = await ApprovalInstanceRepository.list_exceptions(instance.id)
    tasks = await ApprovalQueryRepository.list_tasks_by_approver(1, 7)

    assert saved is not None
    assert saved.status == ApprovalInstanceStatus.EXCEPTION
    assert [one.exception_type for one in exceptions] == [ApprovalExceptionType.SCENARIO_DISABLED]
    assert tasks == []


@pytest.mark.asyncio
async def test_repository_returns_existing_duplicate_pending_instance(patched_approval_repositories):
    await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            scenario_name='频道订阅审批',
            handler_key='channel_subscribe',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.PENDING,
            payload_snapshot={'channel_id': 88},
            detail_snapshot={'channel_name': '资讯频道'},
        )
    )

    duplicate = await ApprovalInstanceRepository.find_duplicate_active_instance(
        tenant_id=1,
        scenario_code='channel_subscribe_request',
        business_key='channel:88:user:7',
        applicant_user_id=7,
    )

    assert duplicate is not None
    assert duplicate.status == ApprovalInstanceStatus.PENDING


@pytest.mark.asyncio
async def test_repository_allows_resubmit_after_closed_instance(patched_approval_repositories):
    await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            scenario_name='频道订阅审批',
            handler_key='channel_subscribe',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.APPROVED,
            payload_snapshot={'channel_id': 88},
            detail_snapshot={'channel_name': '资讯频道'},
        )
    )

    created = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            scenario_name='频道订阅审批',
            handler_key='channel_subscribe',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.PENDING,
            payload_snapshot={'channel_id': 88},
            detail_snapshot={'channel_name': '资讯频道'},
        )
    )

    duplicate = await ApprovalInstanceRepository.find_duplicate_active_instance(
        tenant_id=1,
        scenario_code='channel_subscribe_request',
        business_key='channel:88:user:7',
        applicant_user_id=7,
    )

    assert created.id is not None
    assert duplicate is not None
    assert duplicate.id == created.id


@pytest.mark.asyncio
async def test_user_menu_access_repository_lists_active_grants(patched_approval_repositories):
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=9,
        menu_key='workstation',
        menu_name='工作台',
        grant_source='approval_instance',
        grant_instance_id=11,
    )
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=9,
        menu_key='home',
        menu_name='首页',
        grant_source='approval_instance',
        grant_instance_id=11,
    )
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=10,
        menu_key='apps',
        menu_name='应用中心',
        grant_source='approval_instance',
        grant_instance_id=12,
    )
    await UserMenuAccessRepository.revoke_grant(
        tenant_id=1,
        user_id=9,
        menu_key='workstation',
        grant_source='approval_instance',
        revoked_by_user_id=1,
        revoked_reason='manual revoke',
    )

    user9_keys = await UserMenuAccessRepository.list_active_menu_keys(1, 9)
    user10_keys = await UserMenuAccessRepository.list_active_menu_keys(1, 10)
    revoked = await UserMenuAccessRepository.get_active_grant(1, 9, 'workstation')

    assert user9_keys == ['home']
    assert user10_keys == ['apps']
    assert revoked is None


@pytest.mark.asyncio
async def test_gate_creates_scenario_disabled_exception():
    registry = SimpleNamespace(get_handler=AsyncMock())
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(
            return_value=SimpleNamespace(
                id=1,
                scenario_code='menu_access_request',
                scenario_name='菜单权限申请',
                enabled=False,
            )
        ),
        list_route_rules=AsyncMock(),
        get_active_flow_version=AsyncMock(),
        list_node_definitions=AsyncMock(),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': 101})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(),
    )
    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=AsyncMock(),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='menu_access_request',
            business_key='menu:knowledge:user:7',
            business_resource_type='web_menu',
            business_resource_id='knowledge',
            business_name='知识管理',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'menu_key': 'knowledge'},
        )
    )

    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert result.instance_id == 101
    assert result.exception_type == ApprovalExceptionType.SCENARIO_DISABLED
    instance_repository.create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_pass_when_route_direct_approve():
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={'menu_name': '知识管理'}),
        build_title=AsyncMock(return_value='知识管理'),
        resolve_approvers=AsyncMock(),
    )
    registry = SimpleNamespace(get_handler=AsyncMock(return_value=handler))
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(
            return_value=SimpleNamespace(
                id=1,
                scenario_code='menu_access_request',
                scenario_name='菜单权限申请',
                enabled=True,
            )
        ),
        list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=11, route_type='pass')]),
        get_active_flow_version=AsyncMock(),
        list_node_definitions=AsyncMock(),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': 201})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(),
    )
    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=AsyncMock(return_value=SimpleNamespace(id=11, route_type='pass')),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='menu_access_request',
            business_key='menu:knowledge:user:7',
            business_resource_type='web_menu',
            business_resource_id='knowledge',
            business_name='知识管理',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'menu_key': 'knowledge'},
        )
    )

    assert result.decision == ApprovalGateDecision.PASS
    assert result.instance_id == 201
    assert result.task_ids == []
    instance_repository.create_exception.assert_not_awaited()
    instance_repository.create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_pending_when_route_hits_flow():
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={'space_name': '研发知识空间'}),
        build_title=AsyncMock(return_value='研发知识空间'),
        resolve_approvers=AsyncMock(return_value=[1001, 1002]),
    )
    registry = SimpleNamespace(get_handler=AsyncMock(return_value=handler))
    flow_version = SimpleNamespace(id=21)
    node = SimpleNamespace(
        node_code='first_node',
        node_name='一级审批',
        node_order=1,
        node_mode='or',
        approver_config={'type': 'direct'},
    )
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(
            return_value=SimpleNamespace(
                id=2,
                scenario_code='knowledge_space_subscribe_request',
                scenario_name='知识空间加入审批',
                enabled=True,
            )
        ),
        list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=31, route_type='flow', flow_definition_id=9)]),
        get_active_flow_version=AsyncMock(return_value=flow_version),
        list_node_definitions=AsyncMock(return_value=[node]),
    )

    task_ids = iter([301, 302])

    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': 300})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': next(task_ids)})),
    )
    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=AsyncMock(return_value=SimpleNamespace(id=31, route_type='flow', flow_definition_id=9)),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='knowledge_space_subscribe_request',
            business_key='space:12:user:7',
            business_resource_type='knowledge_space',
            business_resource_id='12',
            business_name='研发知识空间',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'space_id': 12},
        )
    )

    assert result.decision == ApprovalGateDecision.PENDING
    assert result.instance_id == 300
    assert result.task_ids == [301, 302]
    assert instance_repository.create_task.await_count == 2


@pytest.mark.asyncio
async def test_gate_returns_existing_instance_for_duplicate_business_key():
    duplicate = SimpleNamespace(id=401, status=ApprovalInstanceStatus.PENDING)
    gate = ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock()),
        scenario_repository=SimpleNamespace(),
        instance_repository=SimpleNamespace(
            find_duplicate_active_instance=AsyncMock(return_value=duplicate),
            create_instance=AsyncMock(),
            create_exception=AsyncMock(),
            create_task=AsyncMock(),
        ),
        route_matcher=AsyncMock(),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'channel_id': 88},
        )
    )

    assert result.decision == ApprovalGateDecision.PENDING
    assert result.instance_id == 401


@pytest.mark.asyncio
async def test_gate_creates_route_missing_exception():
    handler = SimpleNamespace(build_detail=AsyncMock(return_value={}), build_title=AsyncMock(return_value='频道'), resolve_approvers=AsyncMock())
    registry = SimpleNamespace(get_handler=AsyncMock(return_value=handler))
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(
            return_value=SimpleNamespace(id=1, scenario_code='channel_subscribe_request', scenario_name='频道订阅审批', enabled=True)
        ),
        list_route_rules=AsyncMock(return_value=[]),
        get_active_flow_version=AsyncMock(),
        list_node_definitions=AsyncMock(),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': 501})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(),
    )
    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=AsyncMock(return_value=None),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'channel_id': 88},
        )
    )

    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert result.exception_type == ApprovalExceptionType.ROUTE_MISSING


@pytest.mark.asyncio
async def test_gate_creates_approver_empty_exception():
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={'space_name': '研发知识空间'}),
        build_title=AsyncMock(return_value='研发知识空间'),
        resolve_approvers=AsyncMock(return_value=[]),
    )
    registry = SimpleNamespace(get_handler=AsyncMock(return_value=handler))
    node = SimpleNamespace(
        node_code='first_node',
        node_name='一级审批',
        node_order=1,
        node_mode='or',
        approver_config={'type': 'department_admin'},
    )
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(
            return_value=SimpleNamespace(id=2, scenario_code='knowledge_space_subscribe_request', scenario_name='知识空间加入审批', enabled=True)
        ),
        list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=31, route_type='flow', flow_definition_id=9)]),
        get_active_flow_version=AsyncMock(return_value=SimpleNamespace(id=21)),
        list_node_definitions=AsyncMock(return_value=[node]),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={'id': 601})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(),
    )
    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=AsyncMock(return_value=SimpleNamespace(id=31, route_type='flow', flow_definition_id=9)),
    )

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code='knowledge_space_subscribe_request',
            business_key='space:12:user:7',
            business_resource_type='knowledge_space',
            business_resource_id='12',
            business_name='研发知识空间',
            applicant_user_id=7,
            applicant_user_name='alice',
            payload_snapshot={'space_id': 12},
        )
    )

    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert result.exception_type == ApprovalExceptionType.APPROVER_EMPTY
    instance_repository.create_task.assert_not_awaited()


def test_registry_exposes_default_presets():
    registry = ApprovalRegistry.with_default_presets()

    presets = {preset.scenario_code: preset for preset in registry.list_presets()}

    assert set(presets) == {
        'menu_access_request',
        'channel_subscribe_request',
        'knowledge_space_subscribe_request',
    }
    assert presets['menu_access_request'].handler_key == 'menu_access_request'

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.services.approval_registry import (
    SYSTEM_FILE_CHANGE_SCENARIO_CODE,
    ApprovalRegistry,
    ensure_system_file_change_scenario,
)
from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)
from bisheng.common.init_data import _init_default_approval_scenarios
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id
from bisheng.tenant.domain.services.tenant_service import TenantService


@pytest_asyncio.fixture
async def approval_db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(approval_db_engine):
    async with AsyncSession(bind=approval_db_engine, expire_on_commit=False) as value:
        yield value


@pytest.fixture(autouse=True)
def scenario_tenant_context(request):
    tenant_by_test = {
        "test_fixed_scenario_preset_and_ensure_are_idempotent": 9,
        "test_caller_session_keeps_transaction_and_controls_rollback": 10,
        "test_unique_conflict_savepoint_does_not_rollback_caller_transaction": 11,
        "test_default_startup_bootstrap_uses_fixed_ensure": DEFAULT_TENANT_ID,
    }
    token = current_tenant_id.set(tenant_by_test.get(request.node.name))
    try:
        yield
    finally:
        current_tenant_id.reset(token)


async def _load_fixed_bundle(session: AsyncSession, tenant_id: int):
    scenario = (
        await session.exec(
            select(ApprovalScenario).where(
                ApprovalScenario.tenant_id == tenant_id,
                ApprovalScenario.scenario_code == SYSTEM_FILE_CHANGE_SCENARIO_CODE,
            )
        )
    ).one()
    routes = (await session.exec(select(ApprovalRouteRule).where(ApprovalRouteRule.scenario_id == scenario.id))).all()
    flows = (
        await session.exec(select(ApprovalFlowDefinition).where(ApprovalFlowDefinition.scenario_id == scenario.id))
    ).all()
    versions = (
        await session.exec(
            select(ApprovalFlowVersion).where(
                ApprovalFlowVersion.flow_definition_id == flows[0].id,
                ApprovalFlowVersion.is_active == True,  # noqa: E712 -- DM8 compatible predicate
            )
        )
    ).all()
    nodes = (
        await session.exec(
            select(ApprovalNodeDefinition).where(ApprovalNodeDefinition.flow_version_id == versions[0].id)
        )
    ).all()
    return scenario, routes, flows, versions, nodes


async def test_fixed_scenario_preset_and_ensure_are_idempotent(session):
    preset = ApprovalRegistry.with_default_presets().get_preset(SYSTEM_FILE_CHANGE_SCENARIO_CODE)
    assert preset is not None
    assert preset.handler_key == SYSTEM_FILE_CHANGE_SCENARIO_CODE
    assert preset.condition_fields == ["applicant_role", "action", "resource_type"]
    assert preset.approver_source_types == ["knowledge_space_owner", "knowledge_space_manager"]

    first = await ensure_system_file_change_scenario(tenant_id=9, session=session)
    second = await ensure_system_file_change_scenario(tenant_id=9, session=session)
    assert first.id == second.id

    scenario, routes, flows, versions, nodes = await _load_fixed_bundle(session, 9)
    assert scenario.enabled is True
    assert len(routes) == len(flows) == len(versions) == len(nodes) == 1
    assert routes[0].enabled is True
    assert routes[0].route_type == "flow"
    assert routes[0].match_config == {}
    assert routes[0].flow_definition_id == flows[0].id
    assert flows[0].is_active is True
    assert nodes[0].node_mode == "or"
    assert nodes[0].approver_config == {
        "sources": [
            {"type": "knowledge_space_owner"},
            {"type": "knowledge_space_manager"},
        ]
    }


async def test_caller_session_keeps_transaction_and_controls_rollback(session):
    caller_marker = ApprovalScenario(
        tenant_id=10,
        scenario_code="caller_outer_transaction",
        scenario_name="caller outer transaction",
        enabled=True,
    )
    session.add(caller_marker)
    await ensure_system_file_change_scenario(tenant_id=10, session=session)

    assert session.in_transaction()
    await session.rollback()

    scenarios = (
        await session.exec(
            select(ApprovalScenario).where(
                ApprovalScenario.tenant_id == 10,
            )
        )
    ).all()
    assert scenarios == []


async def test_unique_conflict_savepoint_does_not_rollback_caller_transaction(
    session,
    monkeypatch,
):
    existing = ApprovalScenario(
        tenant_id=11,
        scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
        scenario_name="existing fixed scenario",
        enabled=True,
    )
    session.add(existing)
    await session.commit()
    await session.refresh(existing)

    caller_marker = ApprovalScenario(
        tenant_id=11,
        scenario_code="caller_transaction_marker",
        scenario_name="caller transaction marker",
        enabled=True,
    )
    session.add(caller_marker)
    await session.flush()

    original_exec = session.exec
    exec_count = 0

    class _EmptyResult:
        @staticmethod
        def first():
            return None

    async def _miss_once(*args, **kwargs):
        nonlocal exec_count
        exec_count += 1
        if exec_count == 1:
            return _EmptyResult()
        return await original_exec(*args, **kwargs)

    monkeypatch.setattr(session, "exec", _miss_once)

    result = await ensure_system_file_change_scenario(tenant_id=11, session=session)

    assert result.id == existing.id
    assert session.in_transaction()
    marker = (
        await session.exec(
            select(ApprovalScenario).where(
                ApprovalScenario.tenant_id == 11,
                ApprovalScenario.scenario_code == "caller_transaction_marker",
            )
        )
    ).first()
    assert marker is not None


def _scenario(scenario_id: int = 1) -> ApprovalScenario:
    return ApprovalScenario(
        id=scenario_id,
        tenant_id=7,
        scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
        scenario_name="知识空间文件变更审批",
        enabled=True,
    )


def _route() -> ApprovalRouteRule:
    return ApprovalRouteRule(
        id=2,
        tenant_id=7,
        scenario_id=1,
        route_name="默认分支",
        route_type="flow",
        sort_order=1,
        flow_definition_id=3,
        match_config={},
    )


def _flow() -> ApprovalFlowDefinition:
    return ApprovalFlowDefinition(
        id=3,
        tenant_id=7,
        scenario_id=1,
        flow_code="knowledge_space_file_change_default_flow",
        flow_name="默认文件变更审批流程",
        is_active=True,
    )


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("update_scenario", {"scenario_id": 1, "payload": {"enabled": False}}),
        ("delete_scenario", {"scenario_id": 1}),
        ("create_route", {"scenario_id": 1, "payload": {"route_name": "旁路", "route_type": "pass"}}),
        ("reorder_routes", {"scenario_id": 1, "ordered_route_ids": [2]}),
        ("create_flow", {"scenario_id": 1, "payload": {"flow_name": "旁路流程"}}),
    ],
)
async def test_fixed_scenario_rejects_direct_admin_writes(monkeypatch, method_name, kwargs):
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
        AsyncMock(return_value=_scenario()),
    )
    method = getattr(ApprovalScenarioAdminService, method_name)
    with pytest.raises(ValueError, match="system fixed approval scenario is read-only"):
        await method(tenant_id=7, **kwargs)


@pytest.mark.parametrize(
    ("method_name", "kwargs", "repository_method", "repository_value"),
    [
        ("update_route", {"route_rule_id": 2, "payload": {"route_type": "pass"}}, "get_route_rule", _route()),
        ("delete_route", {"route_rule_id": 2}, "get_route_rule", _route()),
        ("update_flow", {"flow_definition_id": 3, "payload": {"is_active": False}}, "get_flow_definition", _flow()),
        ("delete_flow", {"flow_definition_id": 3}, "get_flow_definition", _flow()),
        ("set_flow_nodes", {"flow_definition_id": 3, "nodes_payload": []}, "get_flow_definition", _flow()),
    ],
)
async def test_fixed_scenario_rejects_nested_admin_writes(
    monkeypatch,
    method_name,
    kwargs,
    repository_method,
    repository_value,
):
    repository = "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository"
    monkeypatch.setattr(f"{repository}.{repository_method}", AsyncMock(return_value=repository_value))
    monkeypatch.setattr(f"{repository}.get_scenario", AsyncMock(return_value=_scenario()))

    method = getattr(ApprovalScenarioAdminService, method_name)
    with pytest.raises(ValueError, match="system fixed approval scenario is read-only"):
        await method(tenant_id=7, **kwargs)


async def test_default_startup_bootstrap_uses_fixed_ensure(session):
    await _init_default_approval_scenarios(session, ensure_system_scenarios=True)

    scenario, routes, flows, versions, nodes = await _load_fixed_bundle(session, DEFAULT_TENANT_ID)
    assert scenario.enabled is True
    assert len(routes) == len(flows) == len(versions) == len(nodes) == 1


async def test_new_tenant_bootstrap_calls_fixed_ensure(monkeypatch):
    tenant = type(
        "TenantRow",
        (),
        {"id": 88, "model_dump": lambda self, include=None: {"id": self.id}},
    )()
    ensure_mock = AsyncMock(return_value=_scenario())
    monkeypatch.setattr(
        "bisheng.tenant.domain.services.tenant_service.TenantDao.aget_by_code",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.tenant.domain.services.tenant_service.TenantDao.acreate_tenant",
        AsyncMock(return_value=tenant),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service.DepartmentService.acreate_root_department",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.tenant.domain.services.tenant_service.UserTenantDao.aadd_user_to_tenant",
        AsyncMock(),
    )
    monkeypatch.setattr(TenantService, "_write_tenant_tuples", AsyncMock())
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.WorkStationService.acopy_root_builtin_tools_to_tenant",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_registry.ensure_system_file_change_scenario",
        ensure_mock,
    )

    data = type(
        "TenantInput",
        (),
        {
            "tenant_name": "Tenant 88",
            "tenant_code": "tenant-88",
            "logo": None,
            "contact_name": None,
            "contact_phone": None,
            "contact_email": None,
            "quota_config": {},
            "admin_user_ids": [7],
        },
    )()
    login_user = type("LoginUser", (), {"user_id": 7})()

    await TenantService.acreate_tenant(data, login_user)

    ensure_mock.assert_awaited_once_with(tenant_id=88)

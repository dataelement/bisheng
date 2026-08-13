from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_decision_outbox import ApprovalDecisionOutbox
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
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.core.context.tenant import current_tenant_id

TENANT_ID = 42
APPROVER_USER_ID = 19
LEGACY_SCENARIOS = (
    ("menu_access_request", "菜单权限申请", "web_menu", "knowledge"),
    ("channel_subscribe_request", "频道订阅审批", "channel", "7"),
    ("knowledge_space_subscribe_request", "知识空间加入审批", "knowledge_space", "8"),
)


@pytest_asyncio.fixture
async def existing_scenario_db(monkeypatch: pytest.MonkeyPatch):
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
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalException.__table__,
        ApprovalOutbox.__table__,
        ApprovalDecisionOutbox.__table__,
        ApprovalActionLog.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        session_factory,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session",
        session_factory,
    )
    tenant_token = current_tenant_id.set(TENANT_ID)
    try:
        yield engine
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


def _handler(*, approver_user_ids: list[int] | None = None):
    return SimpleNamespace(
        build_detail=AsyncMock(return_value={"safe": "snapshot"}),
        build_title=AsyncMock(return_value="legacy request"),
        resolve_approvers=AsyncMock(return_value=approver_user_ids or []),
    )


def _request(*, scenario_code: str, resource_type: str, resource_id: str) -> ApprovalGateRequest:
    return ApprovalGateRequest(
        tenant_id=TENANT_ID,
        scenario_code=scenario_code,
        business_key=f"{scenario_code}:{resource_id}:user:5",
        business_resource_type=resource_type,
        business_resource_id=resource_id,
        business_name="legacy request",
        applicant_user_id=5,
        applicant_user_name="applicant",
        payload_snapshot={"resource_id": resource_id},
    )


async def _seed_scenario(*, scenario_code: str, scenario_name: str) -> ApprovalScenario:
    return await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=TENANT_ID,
            scenario_code=scenario_code,
            scenario_name=scenario_name,
            enabled=True,
        )
    )


async def _seed_pass_route(*, scenario: ApprovalScenario) -> None:
    await ApprovalScenarioRepository.create_route_rule(
        ApprovalRouteRule(
            tenant_id=TENANT_ID,
            scenario_id=scenario.id,
            route_name="direct pass",
            route_type="pass",
            sort_order=1,
            match_config={},
        )
    )


async def _seed_flow_route(
    *,
    scenario: ApprovalScenario,
) -> tuple[ApprovalFlowVersion, ApprovalNodeDefinition]:
    definition = await ApprovalScenarioRepository.create_flow_definition(
        ApprovalFlowDefinition(
            tenant_id=TENANT_ID,
            scenario_id=scenario.id,
            flow_code=f"{scenario.scenario_code}_flow",
            flow_name="legacy approval flow",
            is_active=True,
        )
    )
    version = await ApprovalScenarioRepository.create_flow_version(
        ApprovalFlowVersion(
            tenant_id=TENANT_ID,
            flow_definition_id=definition.id,
            version_no=1,
            is_active=True,
            definition_snapshot={},
        )
    )
    node = await ApprovalScenarioRepository.create_node_definition(
        ApprovalNodeDefinition(
            tenant_id=TENANT_ID,
            flow_version_id=version.id,
            node_code="review",
            node_name="review",
            node_order=1,
            node_mode="or",
            approver_config={"approver_user_ids": [APPROVER_USER_ID]},
            extra_config={},
        )
    )
    await ApprovalScenarioRepository.create_route_rule(
        ApprovalRouteRule(
            tenant_id=TENANT_ID,
            scenario_id=scenario.id,
            route_name="approval flow",
            route_type="flow",
            sort_order=1,
            flow_definition_id=definition.id,
            match_config={},
        )
    )
    return version, node


async def _decision_events(engine, *, instance_id: int) -> list[ApprovalDecisionOutbox]:
    async with AsyncSession(engine) as session:
        statement = select(ApprovalDecisionOutbox).where(ApprovalDecisionOutbox.instance_id == instance_id)
        return list((await session.exec(statement)).all())


@pytest.mark.parametrize(
    ("scenario_code", "scenario_name", "resource_type", "resource_id"),
    LEGACY_SCENARIOS,
)
async def test_existing_scenario_pass_keeps_legacy_outbox_handler_and_dispatch(
    existing_scenario_db,
    scenario_code: str,
    scenario_name: str,
    resource_type: str,
    resource_id: str,
) -> None:
    scenario = await _seed_scenario(scenario_code=scenario_code, scenario_name=scenario_name)
    await _seed_pass_route(scenario=scenario)
    registry = ApprovalRegistry()
    registry.register_handler(scenario_code, _handler())
    gate = ApprovalGate(registry=registry)

    with (
        patch.object(ApprovalGate, "_dispatch_outbox_task") as dispatch,
        patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", new=AsyncMock()),
    ):
        result = await gate.request_or_pass(
            _request(
                scenario_code=scenario_code,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    outboxes = await ApprovalInstanceRepository.list_outbox(result.instance_id)
    assert result.decision == ApprovalGateDecision.PASS
    assert instance.status == ApprovalInstanceStatus.APPROVED
    assert instance.handler_key == scenario_code
    assert len(outboxes) == 1
    assert outboxes[0].handler_key == scenario_code
    assert outboxes[0].status == ApprovalOutboxStatus.PENDING
    assert await _decision_events(existing_scenario_db, instance_id=result.instance_id) == []
    dispatch.assert_called_once_with(outboxes[0].id, TENANT_ID)


@pytest.mark.parametrize(
    ("scenario_code", "scenario_name", "resource_type", "resource_id"),
    LEGACY_SCENARIOS,
)
async def test_existing_scenario_flow_final_node_keeps_legacy_outbox_and_notifications(
    existing_scenario_db,
    scenario_code: str,
    scenario_name: str,
    resource_type: str,
    resource_id: str,
) -> None:
    scenario = await _seed_scenario(scenario_code=scenario_code, scenario_name=scenario_name)
    await _seed_flow_route(scenario=scenario)
    handler = _handler(approver_user_ids=[APPROVER_USER_ID])
    registry = ApprovalRegistry()
    registry.register_handler(scenario_code, handler)
    gate = ApprovalGate(registry=registry)
    with patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", new=AsyncMock()):
        submitted = await gate.request_or_pass(
            _request(
                scenario_code=scenario_code,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )

    service = ApprovalCenterService(instance_repository=ApprovalInstanceRepository)
    runtime_handler = SimpleNamespace()
    with (
        patch(
            "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
            new=AsyncMock(return_value=runtime_handler),
        ),
        patch.object(ApprovalCenterService, "_dispatch_outbox") as dispatch,
        patch.object(ApprovalCenterService, "_write_audit_log", new=AsyncMock()),
        patch.object(ApprovalCenterService, "_send_approval_notify", new=AsyncMock()) as notify,
    ):
        await service.decide_task(
            task_id=submitted.task_ids[0],
            action="approve",
            operator_user_id=APPROVER_USER_ID,
            operator_user_name="reviewer",
            operator_tenant_id=TENANT_ID,
        )

    instance = await ApprovalInstanceRepository.get_instance(submitted.instance_id)
    task = await ApprovalInstanceRepository.get_task(submitted.task_ids[0])
    outboxes = await ApprovalInstanceRepository.list_outbox(submitted.instance_id)
    assert submitted.decision == ApprovalGateDecision.PENDING
    assert task.status == ApprovalTaskStatus.APPROVED
    assert instance.status == ApprovalInstanceStatus.APPROVED
    assert instance.handler_key == scenario_code
    assert len(outboxes) == 1
    assert outboxes[0].handler_key == scenario_code
    assert outboxes[0].status == ApprovalOutboxStatus.PENDING
    assert await _decision_events(existing_scenario_db, instance_id=submitted.instance_id) == []
    dispatch.assert_called_once_with(outboxes[0].id, TENANT_ID)
    assert any(call.kwargs.get("action_code") == "approval_instance_approved" for call in notify.await_args_list)


@pytest.mark.parametrize(
    ("scenario_code", "scenario_name", "resource_type", "resource_id"),
    LEGACY_SCENARIOS,
)
async def test_existing_scenario_route_exception_keeps_admin_notification_without_any_outbox(
    existing_scenario_db,
    scenario_code: str,
    scenario_name: str,
    resource_type: str,
    resource_id: str,
) -> None:
    await _seed_scenario(scenario_code=scenario_code, scenario_name=scenario_name)
    registry = ApprovalRegistry()
    registry.register_handler(scenario_code, _handler())
    gate = ApprovalGate(registry=registry)

    with (
        patch.object(ApprovalGate, "_notify_admins_of_exception", new=AsyncMock()) as notify_admins,
        patch("bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2", new=AsyncMock()),
    ):
        result = await gate.request_or_pass(
            _request(
                scenario_code=scenario_code,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )

    instance = await ApprovalInstanceRepository.get_instance(result.instance_id)
    exceptions = await ApprovalInstanceRepository.list_exceptions(result.instance_id)
    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert instance.status == ApprovalInstanceStatus.EXCEPTION
    assert instance.handler_key == scenario_code
    assert [row.exception_type for row in exceptions] == [ApprovalExceptionType.ROUTE_MISSING]
    assert await ApprovalInstanceRepository.list_outbox(result.instance_id) == []
    assert await _decision_events(existing_scenario_db, instance_id=result.instance_id) == []
    notify_admins.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        applicant_user_id=5,
        exception_type=ApprovalExceptionType.ROUTE_MISSING,
        business_name="legacy request",
        instance_id=result.instance_id,
    )

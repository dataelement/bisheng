from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.repositories.approval_scenario_repository import (
    ApprovalScenarioRepository,
)
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
    ApprovalGateResult,
)
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)
from bisheng.approval.domain.services.department_file_view_approval_service import (
    DepartmentFileViewApprovalService,
)
from bisheng.common.errcode.approval import (
    ApprovalConditionOptionInvalidError,
    ApprovalConfigInUseError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessStatus,
    DepartmentFileResource,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def test_department_file_view_preset_exposes_trusted_route_conditions() -> None:
    preset = ApprovalRegistry.with_default_presets().get_preset(
        "department_file_view_request",
    )

    assert preset is not None
    assert preset.condition_fields == [
        "applicant_role",
        "applicant_department_id",
        "file_department_id",
        "file_knowledge_space_id",
    ]
    descriptors = {descriptor.field: descriptor for descriptor in preset.condition_field_options}
    assert descriptors["applicant_department_id"].selector_type == "department"
    assert descriptors["file_department_id"].selector_type == "department"
    assert descriptors["file_knowledge_space_id"].selector_type == "department_knowledge_space"


@pytest.mark.asyncio
async def test_department_file_view_scenario_structure_is_editable() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
    )
    created = SimpleNamespace(model_dump=lambda: {"id": 9})

    with (
        patch.object(
            ApprovalScenarioRepository,
            "get_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch.object(
            ApprovalScenarioRepository,
            "create_route_rule_safely",
            new=AsyncMock(return_value=created),
        ),
        patch.object(
            ApprovalScenarioAdminService,
            "_validate_route_payload",
            new=AsyncMock(),
        ),
    ):
        result = await ApprovalScenarioAdminService.create_route(
            tenant_id=1,
            scenario_id=1,
            payload={
                "route_name": "部门库分支",
                "route_type": "pass",
                "match_config": {},
            },
        )

    assert result == {"id": 9}


@pytest.mark.asyncio
async def test_condition_options_use_valid_department_space_resolver() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
    )
    expected = {
        "items": [
            {
                "value": "20",
                "label": "炼钢部知识库 (炼钢部)",
                "department_id": 12,
                "department_name": "炼钢部",
            }
        ],
        "total": 1,
        "page": 2,
        "page_size": 10,
    }

    with (
        patch.object(
            ApprovalScenarioRepository,
            "get_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch.object(
            KnowledgeSpaceService,
            "list_valid_department_space_options",
            new=AsyncMock(return_value=expected),
        ) as resolver,
    ):
        result = await ApprovalScenarioAdminService.list_condition_options(
            tenant_id=1,
            scenario_id=1,
            field="file_knowledge_space_id",
            keyword="炼钢",
            page=2,
            page_size=10,
        )

    assert result == expected
    resolver.assert_awaited_once_with(
        keyword="炼钢",
        page=2,
        page_size=10,
    )


@pytest.mark.asyncio
async def test_valid_department_space_options_support_search_and_pagination() -> None:
    bindings = [
        SimpleNamespace(space_id=20, department_id=12),
        SimpleNamespace(space_id=30, department_id=13),
    ]
    spaces = [
        SimpleNamespace(
            id=20,
            name="炼钢部知识库",
            type=KnowledgeTypeEnum.SPACE.value,
        ),
        SimpleNamespace(
            id=30,
            name="轧钢部知识库",
            type=KnowledgeTypeEnum.SPACE.value,
        ),
    ]
    departments = [
        SimpleNamespace(id=12, name="炼钢部", dept_id="LG"),
        SimpleNamespace(id=13, name="轧钢部", dept_id="ZG"),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_all",
            new=AsyncMock(return_value=bindings),
        ),
        patch.object(
            KnowledgeSpaceService,
            "_get_valid_department_space_ids",
            new=AsyncMock(return_value={20, 30}),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=spaces),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
            new=AsyncMock(return_value=departments),
        ),
    ):
        searched = await KnowledgeSpaceService.list_valid_department_space_options(
            keyword="炼钢",
            page=1,
            page_size=20,
        )
        second_page = await KnowledgeSpaceService.list_valid_department_space_options(
            page=2,
            page_size=1,
        )

    assert searched["total"] == 1
    assert searched["items"][0]["value"] == "20"
    assert second_page["total"] == 2
    assert second_page["items"][0]["value"] == "30"


@pytest.mark.asyncio
async def test_route_save_revalidates_department_space_option() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
    )
    payload = {
        "route_name": "炼钢部知识库",
        "route_type": "pass",
        "flow_definition_id": None,
        "match_config": {
            "field": "file_knowledge_space_id",
            "value": "20",
        },
    }

    with patch.object(
        KnowledgeSpaceService,
        "is_valid_department_space_id",
        new=AsyncMock(return_value=True),
    ) as resolver:
        await ApprovalScenarioAdminService._validate_route_payload(
            tenant_id=1,
            scenario=scenario,
            payload=payload,
        )
    resolver.assert_awaited_once_with(20)

    with patch.object(
        KnowledgeSpaceService,
        "is_valid_department_space_id",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(ApprovalConditionOptionInvalidError):
            await ApprovalScenarioAdminService._validate_route_payload(
                tenant_id=1,
                scenario=scenario,
                payload=payload,
            )


@pytest.mark.asyncio
async def test_route_save_rejects_non_and_match_operator() -> None:
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="menu_access_request",
    )
    payload = {
        "route_name": "OR 不被支持",
        "route_type": "pass",
        "flow_definition_id": None,
        "match_config": {
            "operator": "or",
            "conditions": [
                {"field": "applicant_role", "value": "admin"},
                {"field": "menu_key", "value": "knowledge"},
            ],
        },
    }

    with pytest.raises(ApprovalConditionOptionInvalidError):
        await ApprovalScenarioAdminService._validate_route_payload(
            tenant_id=1,
            scenario=scenario,
            payload=payload,
        )


@pytest.mark.asyncio
async def test_route_matcher_accepts_only_trusted_department_file_context() -> None:
    gate = ApprovalGate(registry=ApprovalRegistry.with_default_presets())
    routes = [
        SimpleNamespace(
            id=1,
            enabled=True,
            match_config={
                "operator": "and",
                "conditions": [
                    {"field": "file_department_id", "value": "12"},
                    {"field": "file_knowledge_space_id", "value": "20"},
                ],
            },
        ),
        SimpleNamespace(id=2, enabled=True, match_config={}),
    ]
    request = ApprovalGateRequest(
        tenant_id=1,
        scenario_code="department_file_view_request",
        business_key="department-file:20:30",
        business_resource_type="department_knowledge_file",
        business_resource_id="30",
        business_name="制度.pdf",
        applicant_user_id=9,
        applicant_user_name="申请人",
        payload_snapshot={
            "file_department_id": 12,
            "file_knowledge_space_id": 20,
        },
    )

    matched = await gate._match_first_route(routes, request)

    assert matched.id == 1


@pytest_asyncio.fixture
async def config_lifecycle_session_factory(monkeypatch):
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
    ]
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: SQLModel.metadata.create_all(
                sync_connection,
                tables=tables,
            )
        )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session",
        factory,
    )
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_referenced_route_cannot_be_physically_deleted(
    config_lifecycle_session_factory,
) -> None:
    async with config_lifecycle_session_factory() as session:
        scenario = ApprovalScenario(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            enabled=True,
        )
        session.add(scenario)
        await session.flush()
        route = ApprovalRouteRule(
            tenant_id=1,
            scenario_id=int(scenario.id),
            route_name="默认分支",
            route_type="pass",
        )
        session.add(route)
        await session.flush()
        session.add(
            ApprovalInstance(
                tenant_id=1,
                scenario_code=scenario.scenario_code,
                scenario_name=scenario.scenario_name,
                handler_key=scenario.scenario_code,
                business_key="department-file:20:30",
                business_resource_type="department_knowledge_file",
                business_resource_id="30",
                business_name="制度.pdf",
                applicant_user_id=9,
                applicant_user_name="申请人",
                route_rule_id=int(route.id),
                status="approved",
            )
        )
        route_id = int(route.id)
        await session.commit()

    with pytest.raises(ApprovalConfigInUseError):
        await ApprovalScenarioRepository.delete_route_rule_safely(
            tenant_id=1,
            route_rule_id=route_id,
        )

    assert await ApprovalScenarioRepository.get_route_rule(route_id) is not None


@pytest.mark.asyncio
async def test_unreferenced_route_can_be_physically_deleted(
    config_lifecycle_session_factory,
) -> None:
    async with config_lifecycle_session_factory() as session:
        scenario = ApprovalScenario(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            enabled=True,
        )
        session.add(scenario)
        await session.flush()
        route = ApprovalRouteRule(
            tenant_id=1,
            scenario_id=int(scenario.id),
            route_name="未使用分支",
            route_type="pass",
        )
        session.add(route)
        await session.flush()
        route_id = int(route.id)
        await session.commit()

    assert await ApprovalScenarioRepository.delete_route_rule_safely(
        tenant_id=1,
        route_rule_id=route_id,
    )
    assert await ApprovalScenarioRepository.get_route_rule(route_id) is None


@pytest.mark.asyncio
async def test_node_edit_creates_new_version_and_preserves_historical_nodes(
    config_lifecycle_session_factory,
) -> None:
    async with config_lifecycle_session_factory() as session:
        scenario = ApprovalScenario(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            enabled=True,
        )
        session.add(scenario)
        await session.flush()
        flow = ApprovalFlowDefinition(
            tenant_id=1,
            scenario_id=int(scenario.id),
            flow_code="department_file_view",
            flow_name="部门文件查看审批流",
            is_active=True,
        )
        session.add(flow)
        await session.flush()
        old_version = ApprovalFlowVersion(
            tenant_id=1,
            flow_definition_id=int(flow.id),
            version_no=1,
            is_active=True,
            definition_snapshot={"nodes": [{"node_code": "old"}]},
        )
        session.add(old_version)
        await session.flush()
        old_node = ApprovalNodeDefinition(
            tenant_id=1,
            flow_version_id=int(old_version.id),
            node_code="old",
            node_name="旧审批节点",
            node_order=0,
            node_mode="or",
            approver_config={"sources": ["department_file_approvers"]},
        )
        session.add(old_node)
        await session.flush()
        historical_instance = ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key=scenario.scenario_code,
            business_key="department-file:20:30",
            business_resource_type="department_knowledge_file",
            business_resource_id="30",
            business_name="制度.pdf",
            applicant_user_id=9,
            applicant_user_name="申请人",
            flow_version_id=int(old_version.id),
            status="pending",
        )
        session.add(historical_instance)
        await session.flush()
        flow_id = int(flow.id)
        old_version_id = int(old_version.id)
        old_node_id = int(old_node.id)
        instance_id = int(historical_instance.id)
        await session.commit()

    _, new_version, created_nodes, _ = await ApprovalScenarioRepository.replace_flow_nodes_safely(
        tenant_id=1,
        flow_definition_id=flow_id,
        nodes_payload=[
            {
                "node_code": "new",
                "node_name": "新审批节点",
                "node_order": 0,
                "node_mode": "and",
                "approver_config": {
                    "sources": ["knowledge_space_owner"],
                },
            }
        ],
    )

    async with config_lifecycle_session_factory() as session:
        persisted_old_version = await session.get(
            ApprovalFlowVersion,
            old_version_id,
        )
        persisted_old_node = await session.get(
            ApprovalNodeDefinition,
            old_node_id,
        )
        persisted_instance = await session.get(ApprovalInstance, instance_id)

    assert persisted_old_version is not None
    assert persisted_old_version.is_active is False
    assert persisted_old_node is not None
    assert persisted_instance is not None
    assert persisted_instance.flow_version_id == old_version_id
    assert int(new_version.id) != old_version_id
    assert new_version.version_no == 2
    assert new_version.is_active is True
    assert [node.node_code for node in created_nodes] == ["new"]


@pytest.mark.asyncio
async def test_flow_with_historical_version_reference_cannot_be_deleted(
    config_lifecycle_session_factory,
) -> None:
    async with config_lifecycle_session_factory() as session:
        scenario = ApprovalScenario(
            tenant_id=1,
            scenario_code="department_file_view_request",
            scenario_name="部门文件查看审批",
            enabled=True,
        )
        session.add(scenario)
        await session.flush()
        flow = ApprovalFlowDefinition(
            tenant_id=1,
            scenario_id=int(scenario.id),
            flow_code="historical_flow",
            flow_name="历史审批流",
            is_active=False,
        )
        session.add(flow)
        await session.flush()
        version = ApprovalFlowVersion(
            tenant_id=1,
            flow_definition_id=int(flow.id),
            version_no=1,
            is_active=False,
            definition_snapshot={},
        )
        session.add(version)
        await session.flush()
        session.add(
            ApprovalInstance(
                tenant_id=1,
                scenario_code=scenario.scenario_code,
                scenario_name=scenario.scenario_name,
                handler_key=scenario.scenario_code,
                business_key="department-file:20:30",
                business_resource_type="department_knowledge_file",
                business_resource_id="30",
                business_name="制度.pdf",
                applicant_user_id=9,
                applicant_user_name="申请人",
                flow_version_id=int(version.id),
                status="approved",
            )
        )
        flow_id = int(flow.id)
        await session.commit()

    with pytest.raises(ApprovalConfigInUseError):
        await ApprovalScenarioRepository.delete_flow_definition_safely(
            tenant_id=1,
            flow_definition_id=flow_id,
        )

    assert await ApprovalScenarioRepository.get_flow_definition(flow_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_first", [False, True])
async def test_apply_and_route_delete_interleavings_have_no_dangling_route_id(
    delete_first: bool,
) -> None:
    lock = asyncio.Lock()
    route_read = asyncio.Event()
    allow_application = asyncio.Event()
    delete_locked = asyncio.Event()
    allow_delete = asyncio.Event()
    state = SimpleNamespace(
        route_exists=True,
        pending_reference=False,
        referenced=False,
    )
    route = SimpleNamespace(
        id=2,
        tenant_id=1,
        scenario_id=1,
        route_name="无需审批",
        route_type="pass",
        enabled=True,
        match_config={},
    )
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
        scenario_name="部门文件查看审批",
        enabled=True,
    )

    class RaceSession:
        def __init__(self) -> None:
            self.holds_route_lock = False

        def add(self, _row) -> None:
            return None

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            state.referenced = bool(state.referenced or state.pending_reference)
            if self.holds_route_lock:
                self.holds_route_lock = False
                lock.release()

    session = RaceSession()

    async def list_route_rules(*_args, **_kwargs):
        await lock.acquire()
        session.holds_route_lock = True
        route_read.set()
        if not delete_first:
            await allow_application.wait()
        return [route] if state.route_exists else []

    async def create_instance(row, **_kwargs):
        state.pending_reference = row.route_rule_id is not None
        return row.model_copy(update={"id": 10})

    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(return_value=scenario),
        list_route_rules=AsyncMock(side_effect=list_route_rules),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=create_instance),
        create_outbox=AsyncMock(side_effect=lambda row, **_: row.model_copy(update={"id": 11})),
        create_exception=AsyncMock(side_effect=lambda row, **_: row.model_copy(update={"id": 12})),
    )
    gate = ApprovalGate(
        registry=SimpleNamespace(
            get_handler=AsyncMock(
                return_value=SimpleNamespace(
                    build_detail=AsyncMock(return_value={}),
                    build_title=AsyncMock(return_value="制度.pdf"),
                )
            ),
        ),
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        session=session,
    )
    gate._dispatch_outbox_task = Mock()
    gate._notify_admins_of_exception = AsyncMock()

    async def delete_route() -> str:
        await lock.acquire()
        delete_locked.set()
        if delete_first:
            await allow_delete.wait()
        try:
            if state.referenced:
                return "conflict"
            state.route_exists = False
            return "deleted"
        finally:
            lock.release()

    request = ApprovalGateRequest(
        tenant_id=1,
        scenario_code="department_file_view_request",
        business_key="department-file:20:30",
        business_resource_type="department_knowledge_file",
        business_resource_id="30",
        business_name="制度.pdf",
        applicant_user_id=9,
        applicant_user_name="申请人",
        payload_snapshot={
            "file_department_id": 12,
            "file_knowledge_space_id": 20,
        },
    )

    if delete_first:
        delete_task = asyncio.create_task(delete_route())
        await delete_locked.wait()
        apply_task = asyncio.create_task(gate.request_or_pass(request))
        allow_delete.set()
    else:
        apply_task = asyncio.create_task(gate.request_or_pass(request))
        await route_read.wait()
        delete_task = asyncio.create_task(delete_route())
        await asyncio.sleep(0)
        allow_application.set()

    result, delete_result = await asyncio.gather(
        apply_task,
        delete_task,
    )

    if delete_first:
        assert delete_result == "deleted"
        assert result.decision == ApprovalGateDecision.EXCEPTION
        assert result.exception_type == "route_missing"
        assert state.route_exists is False
        assert state.pending_reference is False
    else:
        assert delete_result == "conflict"
        assert result.decision == ApprovalGateDecision.PASS
        assert state.route_exists is True
        assert state.referenced is True


@pytest.mark.asyncio
async def test_gate_holds_locked_route_until_shared_transaction_commit() -> None:
    session = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={"file_name": "制度.pdf"}),
        build_title=AsyncMock(return_value="查看部门文件: 制度.pdf"),
    )
    scenario = SimpleNamespace(
        id=1,
        tenant_id=1,
        scenario_code="department_file_view_request",
        scenario_name="部门文件查看审批",
        enabled=True,
    )
    route = SimpleNamespace(
        id=2,
        tenant_id=1,
        scenario_id=1,
        route_name="无需审批",
        route_type="pass",
        enabled=True,
        match_config={},
    )
    scenario_repository = SimpleNamespace(
        get_scenario_by_code=AsyncMock(return_value=scenario),
        list_route_rules=AsyncMock(return_value=[route]),
    )
    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row, **_: row.model_copy(update={"id": 10})),
        create_outbox=AsyncMock(side_effect=lambda row, **_: row.model_copy(update={"id": 11})),
    )
    gate = ApprovalGate(
        registry=SimpleNamespace(
            get_handler=AsyncMock(return_value=handler),
        ),
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        session=session,
    )
    gate._dispatch_outbox_task = Mock()

    result = await gate.request_or_pass(
        ApprovalGateRequest(
            tenant_id=1,
            scenario_code="department_file_view_request",
            business_key="department-file:20:30",
            business_resource_type="department_knowledge_file",
            business_resource_id="30",
            business_name="制度.pdf",
            applicant_user_id=9,
            applicant_user_name="申请人",
            payload_snapshot={
                "file_department_id": 12,
                "file_knowledge_space_id": 20,
            },
        )
    )

    assert result.decision.value == "pass"
    scenario_repository.list_route_rules.assert_awaited_once_with(
        1,
        1,
        session=session,
        for_update=True,
        enabled_only=True,
    )
    instance_repository.create_instance.assert_awaited_once()
    assert instance_repository.create_instance.await_args.kwargs["session"] is session
    assert instance_repository.create_outbox.await_args.kwargs["session"] is session
    session.commit.assert_awaited_once()
    gate._dispatch_outbox_task.assert_called_once_with(11)


@pytest.mark.asyncio
async def test_apply_builds_route_context_from_live_resource() -> None:
    file = SimpleNamespace(
        id=30,
        knowledge_id=20,
        file_name="制度.pdf",
    )
    decision = DepartmentFileAccessDecision(
        file_id=30,
        space_id=20,
        status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        department_id=12,
    )
    resource = DepartmentFileResource(
        file=file,
        space=SimpleNamespace(id=20, name="炼钢部知识库"),
        scope=SimpleNamespace(),
        binding=SimpleNamespace(department_id=12),
        department=SimpleNamespace(id=12, name="炼钢部"),
        valid=True,
    )
    service = DepartmentFileViewApprovalService(
        session=AsyncMock(),
        file_repository=SimpleNamespace(
            find_by_id_for_update=AsyncMock(return_value=file),
        ),
        access_service=SimpleNamespace(
            evaluate_file=AsyncMock(return_value=decision),
            load_resource=AsyncMock(return_value=resource),
            resolve_department_approvers=AsyncMock(return_value={20}),
        ),
    )
    service._get_applicant_department_id = AsyncMock(return_value=7)

    with patch.object(
        ApprovalGate,
        "request_or_pass",
        new=AsyncMock(
            return_value=ApprovalGateResult(
                decision=ApprovalGateDecision.PENDING,
                instance_id=99,
                task_ids=[100],
            )
        ),
    ) as request_or_pass:
        await service.apply(
            login_user=SimpleNamespace(
                tenant_id=1,
                user_id=9,
                user_name="申请人",
            ),
            space_id=20,
            file_id=30,
            reason="项目需要",
        )

    gate_request = request_or_pass.await_args.args[0]
    assert gate_request.applicant_department_id == 7
    assert gate_request.payload_snapshot["file_department_id"] == 12
    assert gate_request.payload_snapshot["file_knowledge_space_id"] == 20
    assert gate_request.payload_snapshot["space_id"] == 20
    assert gate_request.payload_snapshot["file_id"] == 30

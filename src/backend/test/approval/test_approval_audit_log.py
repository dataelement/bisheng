"""Regression tests for PRD §9.1 audit-log emission.

These cover the audit writes that previous releases either skipped or
mislabelled. Each test patches only the DAO entry points so the production
service code runs end-to-end inside the test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.approval.domain.models.approval_instance import (
    ApprovalExceptionType,
    ApprovalInstanceStatus,
)
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
)
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)


class _FakeScenario:
    def __init__(self, **kw):
        self.id = kw.get("id", 42)
        self.tenant_id = kw.get("tenant_id", 1)
        self.scenario_code = kw.get("scenario_code", "menu_access_request")
        self.scenario_name = kw.get("scenario_name", "菜单权限申请")
        self.enabled = kw.get("enabled", True)
        self.display_name = kw.get("display_name")

    def model_dump(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "scenario_code": self.scenario_code,
            "scenario_name": self.scenario_name,
            "enabled": self.enabled,
            "display_name": self.display_name,
        }


async def test_update_scenario_writes_toggle_audit_when_enabled_flips():
    scenario = _FakeScenario(enabled=True)
    captured: list[dict] = []

    async def fake_ainsert_v2(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id=999)

    with (
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service."
            "ApprovalScenarioRepository.update_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.AuditLogDao.ainsert_v2",
            new=AsyncMock(side_effect=fake_ainsert_v2),
        ),
    ):
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=1,
            scenario_id=42,
            payload={"enabled": False},
            operator_user_id=7,
            operator_user_name="admin",
            ip_address="10.0.0.1",
        )

    assert len(captured) == 1, "audit log not written on enabled flip"
    row = captured[0]
    assert row["action"] == "approval.scenario.toggle"
    assert row["target_type"] == "approval_scenario"
    assert row["target_id"] == "42"
    assert row["operator_id"] == 7
    assert row["ip_address"] == "10.0.0.1"
    assert row["metadata"]["scenario_code"] == "menu_access_request"
    assert row["metadata"]["before_enabled"] is True
    assert row["metadata"]["after_enabled"] is False


async def test_update_scenario_skips_toggle_audit_when_enabled_unchanged():
    scenario = _FakeScenario(enabled=True)
    captured: list[dict] = []

    with (
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service."
            "ApprovalScenarioRepository.update_scenario",
            new=AsyncMock(return_value=scenario),
        ),
        patch(
            "bisheng.approval.domain.services.approval_scenario_admin_service.AuditLogDao.ainsert_v2",
            new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
        ),
    ):
        # Same enabled value: rename only, no toggle.
        await ApprovalScenarioAdminService.update_scenario(
            tenant_id=1,
            scenario_id=42,
            payload={"enabled": True, "scenario_name": "renamed"},
            operator_user_id=7,
            operator_user_name="admin",
        )

    assert captured == [], "toggle audit must not fire when enabled unchanged"


async def test_outbox_success_emits_handler_success_audit():
    captured: list[dict] = []

    instance = SimpleNamespace(
        id=11,
        tenant_id=1,
        scenario_code="menu_access_request",
        handler_key="menu_access_request",
        business_name="菜单权限申请",
        status="approved",
    )
    outbox = SimpleNamespace(
        id=77,
        instance_id=11,
        status="pending",
        retry_count=0,
        error_summary=None,
        payload_snapshot={"menu_key": "flow"},
    )

    repo = SimpleNamespace(
        get_outbox=AsyncMock(return_value=outbox),
        update_outbox=AsyncMock(),
        get_instance=AsyncMock(return_value=instance),
        update_instance=AsyncMock(),
        create_exception=AsyncMock(),
    )

    with patch(
        "bisheng.approval.domain.services.approval_outbox_service.AuditLogDao.ainsert_v2",
        new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
    ):
        service = ApprovalOutboxService(instance_repository=repo)
        result = await service.execute_outbox(outbox_id=77, executor=lambda _outbox: (True, None))

    assert result is True
    assert len(captured) == 1
    row = captured[0]
    assert row["action"] == "approval.handler.success"
    assert row["operator_id"] == 0  # system
    assert row["metadata"]["outbox_id"] == 77
    assert row["metadata"]["handler"] == "menu_access_request"
    assert row["metadata"]["business_result"] == "success"


async def test_outbox_failure_emits_handler_failed_audit_with_error_summary():
    captured: list[dict] = []
    instance = SimpleNamespace(
        id=11,
        tenant_id=1,
        scenario_code="menu_access_request",
        handler_key="menu_access_request",
        business_name="菜单权限申请",
        status="approved",
    )
    outbox = SimpleNamespace(
        id=77,
        instance_id=11,
        status="pending",
        retry_count=0,
        error_summary=None,
        payload_snapshot={"menu_key": "flow"},
    )
    repo = SimpleNamespace(
        get_outbox=AsyncMock(return_value=outbox),
        update_outbox=AsyncMock(),
        get_instance=AsyncMock(return_value=instance),
        update_instance=AsyncMock(),
        create_exception=AsyncMock(),
    )

    with patch(
        "bisheng.approval.domain.services.approval_outbox_service.AuditLogDao.ainsert_v2",
        new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
    ):
        service = ApprovalOutboxService(instance_repository=repo)
        result = await service.execute_outbox(
            outbox_id=77,
            executor=lambda _outbox: (False, "boom: downstream 500"),
        )

    assert result is False
    assert len(captured) == 1
    row = captured[0]
    assert row["action"] == "approval.handler.failed"
    assert row["reason"] == "boom: downstream 500"
    assert row["metadata"]["error_stack_summary"] == "boom: downstream 500"
    assert row["metadata"]["payload_snapshot"] == {"menu_key": "flow"}


async def _run_gate_for_exception(*, exception_type: str):
    """Drive ApprovalGate.request_or_pass into an exception branch.

    Patches AuditLogDao.ainsert_v2 to capture audit kwargs without touching the
    real DB, and tailors the scenario/route stubs to reproduce either the
    route-missing or approver-empty exception.
    """
    captured: list[dict] = []

    handler = SimpleNamespace(
        build_detail=AsyncMock(return_value={"menu_name": "知识管理"}),
        build_title=AsyncMock(return_value="知识管理"),
        resolve_approvers=AsyncMock(
            return_value=[] if exception_type == ApprovalExceptionType.APPROVER_EMPTY else None
        ),
    )
    registry = SimpleNamespace(get_handler=AsyncMock(return_value=handler))

    if exception_type == ApprovalExceptionType.ROUTE_MISSING:
        scenario_repository = SimpleNamespace(
            get_scenario_by_code=AsyncMock(
                return_value=SimpleNamespace(
                    id=1,
                    scenario_code="menu_access_request",
                    scenario_name="菜单权限申请",
                    enabled=True,
                )
            ),
            list_route_rules=AsyncMock(return_value=[]),
            get_active_flow_version=AsyncMock(),
            list_node_definitions=AsyncMock(),
        )
        route_matcher = AsyncMock(return_value=None)
    else:  # approver_empty: route hits a flow but the first node yields no approvers
        node = SimpleNamespace(
            node_code="first_node",
            node_name="一级审批",
            node_order=1,
            node_mode="or",
            approver_config={"type": "department_admin"},
        )
        scenario_repository = SimpleNamespace(
            get_scenario_by_code=AsyncMock(
                return_value=SimpleNamespace(
                    id=2,
                    scenario_code="knowledge_space_subscribe_request",
                    scenario_name="知识空间加入审批",
                    enabled=True,
                )
            ),
            list_route_rules=AsyncMock(return_value=[SimpleNamespace(id=31, route_type="flow", flow_definition_id=9)]),
            get_active_flow_version=AsyncMock(return_value=SimpleNamespace(id=21)),
            list_node_definitions=AsyncMock(return_value=[node]),
        )
        route_matcher = AsyncMock(return_value=SimpleNamespace(id=31, route_type="flow", flow_definition_id=9))

    instance_repository = SimpleNamespace(
        find_duplicate_active_instance=AsyncMock(return_value=None),
        create_instance=AsyncMock(side_effect=lambda row: row.model_copy(update={"id": 901})),
        create_exception=AsyncMock(),
        create_task=AsyncMock(),
    )

    gate = ApprovalGate(
        registry=registry,
        scenario_repository=scenario_repository,
        instance_repository=instance_repository,
        route_matcher=route_matcher,
    )

    request_kwargs = {
        "tenant_id": 1,
        "business_key": "menu:knowledge:user:7",
        "business_resource_type": "web_menu",
        "business_resource_id": "knowledge",
        "business_name": "知识管理",
        "applicant_user_id": 7,
        "applicant_user_name": "alice",
        "reason": "需要权限",
        "ip_address": "10.0.0.42",
    }
    if exception_type == ApprovalExceptionType.ROUTE_MISSING:
        request_kwargs["scenario_code"] = "menu_access_request"
        request_kwargs["payload_snapshot"] = {"menu_key": "knowledge"}
    else:
        request_kwargs["scenario_code"] = "knowledge_space_subscribe_request"
        request_kwargs["business_key"] = "space:12:user:7"
        request_kwargs["business_resource_type"] = "knowledge_space"
        request_kwargs["business_resource_id"] = "12"
        request_kwargs["business_name"] = "研发知识空间"
        request_kwargs["payload_snapshot"] = {"space_id": 12}

    with (
        patch(
            "bisheng.approval.domain.services.approval_gate.AuditLogDao.ainsert_v2",
            new=AsyncMock(side_effect=lambda **kw: captured.append(kw)),
        ),
        patch.object(ApprovalGate, "_notify_admins_of_exception", new=AsyncMock()),
    ):
        result = await gate.request_or_pass(ApprovalGateRequest(**request_kwargs))

    assert result.decision == ApprovalGateDecision.EXCEPTION
    assert result.exception_type == exception_type
    return captured, result


async def test_gate_emits_submit_audit_when_route_missing_exception():
    captured, result = await _run_gate_for_exception(
        exception_type=ApprovalExceptionType.ROUTE_MISSING,
    )

    assert len(captured) == 1, "submit audit log must be written even when instance hits route_missing exception"
    row = captured[0]
    assert row["action"] == "approval.request.submit"
    assert row["target_type"] == "approval_instance"
    assert row["target_id"] == str(result.instance_id)
    assert row["operator_id"] == 7
    assert row["operator_name"] == "alice"
    assert row["ip_address"] == "10.0.0.42"
    assert row["reason"] == "需要权限"
    assert row["metadata"]["scenario_code"] == "menu_access_request"
    assert row["metadata"]["exception_type"] == ApprovalExceptionType.ROUTE_MISSING
    assert row["metadata"]["instance_status"] == ApprovalInstanceStatus.EXCEPTION


async def test_gate_emits_submit_audit_when_approver_empty_exception():
    captured, result = await _run_gate_for_exception(
        exception_type=ApprovalExceptionType.APPROVER_EMPTY,
    )

    assert len(captured) == 1, "submit audit log must be written even when first node has no approvers"
    row = captured[0]
    assert row["action"] == "approval.request.submit"
    assert row["target_id"] == str(result.instance_id)
    assert row["metadata"]["exception_type"] == ApprovalExceptionType.APPROVER_EMPTY
    assert row["metadata"]["flow_version_id"] == 21
    assert row["metadata"]["route_rule_id"] == 31
    assert row["metadata"]["current_node_name"] == "一级审批"

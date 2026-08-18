# ruff: noqa: RUF002, RUF003
"""转公开适配审批中心：qa_publish_* 为准，instance/task 只做待我处理看板。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
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
from bisheng.common.utils.beijing_time import now_beijing, to_beijing_iso

# 与 publish_service 状态字面量对齐；本模块不反向 import，避免循环。
DECISION_APPROVED = "approved"
DECISION_DEFAULT_APPROVED = "default_approved"
DECISION_PENDING = "pending"
DECISION_REJECTED = "rejected"
PUBLISH_APPROVED = "approved"
PUBLISH_ENDED = "ended"
PUBLISH_EXPIRED = "expired"
PUBLISH_PENDING = "pending"
PUBLISH_REJECTED = "rejected"

QA_PUBLISH_SCENARIO = "qa_question_publish"
QA_PUBLISH_SCENARIO_NAME = "专家问答转公开"
QA_PUBLISH_FLOW_CODE = "qa_question_publish_default"
QA_PUBLISH_NODE_CODE = "qa_publish_and"
QA_PUBLISH_NODE_NAME = "回答专家会签"
QA_PUBLISH_BUSINESS_TYPE = "qa_question"


@dataclass(frozen=True)
class QaPublishFlowContract:
    """租户内转公开待办所需的流程版本与会签节点。"""

    flow_version_id: int
    node_code: str
    node_name: str
    node_order: int
    route_rule_id: int | None
    scenario_name: str


def business_key_for(request_id: int) -> str:
    """instance.business_key，用来反查 qa_publish_request。"""
    return f"qa_publish:{int(request_id)}"


def request_id_from_payload(payload: dict[str, Any] | None) -> int | None:
    """从审批实例快照取出转公开申请 ID。"""
    if not payload:
        return None
    raw = payload.get("request_id") or payload.get("qa_publish_request_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def ensure_flow_contract(tenant_id: int) -> QaPublishFlowContract:
    """幂等预置场景/流程/会签节点，给 approval_task.flow_version_id 用。"""
    tenant_id = int(tenant_id or 1)
    scenario = await ApprovalScenarioRepository.get_scenario_by_code(tenant_id, QA_PUBLISH_SCENARIO)
    if scenario is None:
        scenario = await ApprovalScenarioRepository.create_scenario(
            ApprovalScenario(
                tenant_id=tenant_id,
                scenario_code=QA_PUBLISH_SCENARIO,
                scenario_name=QA_PUBLISH_SCENARIO_NAME,
                enabled=True,
                display_name=QA_PUBLISH_SCENARIO_NAME,
            )
        )
    elif not scenario.enabled:
        scenario.enabled = True
        scenario = await ApprovalScenarioRepository.update_scenario(scenario)

    flows = await ApprovalScenarioRepository.list_flow_definitions(tenant_id, int(scenario.id))
    flow = next((row for row in flows if row.flow_code == QA_PUBLISH_FLOW_CODE), None)
    if flow is None:
        flow = await ApprovalScenarioRepository.create_flow_definition(
            ApprovalFlowDefinition(
                tenant_id=tenant_id,
                scenario_id=int(scenario.id),
                flow_code=QA_PUBLISH_FLOW_CODE,
                flow_name=QA_PUBLISH_SCENARIO_NAME,
                is_active=True,
            )
        )
    version = await ApprovalScenarioRepository.get_active_flow_version(tenant_id, int(flow.id))
    if version is None:
        version = await ApprovalScenarioRepository.create_flow_version(
            ApprovalFlowVersion(
                tenant_id=tenant_id,
                flow_definition_id=int(flow.id),
                version_no=1,
                is_active=True,
                definition_snapshot={"nodes": [QA_PUBLISH_NODE_CODE]},
            )
        )
    nodes = await ApprovalScenarioRepository.list_node_definitions(tenant_id, int(version.id))
    node = next((row for row in nodes if row.node_code == QA_PUBLISH_NODE_CODE), None)
    if node is None:
        node = await ApprovalScenarioRepository.create_node_definition(
            ApprovalNodeDefinition(
                tenant_id=tenant_id,
                flow_version_id=int(version.id),
                node_code=QA_PUBLISH_NODE_CODE,
                node_name=QA_PUBLISH_NODE_NAME,
                node_order=1,
                node_mode="and",
                approver_config={"sources": [{"type": "direct_user", "user_ids": []}]},
                extra_config={},
            )
        )
    routes = await ApprovalScenarioRepository.list_route_rules(tenant_id, int(scenario.id))
    route = next((row for row in routes if int(row.flow_definition_id or 0) == int(flow.id)), None)
    if route is None:
        route = await ApprovalScenarioRepository.create_route_rule(
            ApprovalRouteRule(
                tenant_id=tenant_id,
                scenario_id=int(scenario.id),
                route_name="默认会签",
                route_type="flow",
                sort_order=0,
                flow_definition_id=int(flow.id),
                match_config={},
                enabled=True,
            )
        )
    return QaPublishFlowContract(
        flow_version_id=int(version.id),
        node_code=str(node.node_code),
        node_name=str(node.node_name),
        node_order=int(node.node_order or 1),
        route_rule_id=int(route.id) if route and route.id else None,
        scenario_name=str(scenario.scenario_name or QA_PUBLISH_SCENARIO_NAME),
    )


def _instance_status_for(publish_status: str) -> str:
    mapping = {
        PUBLISH_PENDING: ApprovalInstanceStatus.PENDING,
        PUBLISH_APPROVED: ApprovalInstanceStatus.EXECUTED,
        PUBLISH_REJECTED: ApprovalInstanceStatus.REJECTED,
        PUBLISH_EXPIRED: ApprovalInstanceStatus.CANCELLED,
        PUBLISH_ENDED: ApprovalInstanceStatus.CANCELLED,
    }
    return mapping.get(str(publish_status), ApprovalInstanceStatus.PENDING)


def _task_status_for(decision: str) -> str:
    if decision in {DECISION_APPROVED, DECISION_DEFAULT_APPROVED}:
        return ApprovalTaskStatus.APPROVED
    if decision == DECISION_REJECTED:
        return ApprovalTaskStatus.REJECTED
    if decision == DECISION_PENDING:
        return ApprovalTaskStatus.PENDING
    return ApprovalTaskStatus.CANCELLED


async def _get_instance(request) -> ApprovalInstance | None:
    tenant_id = int(getattr(request, "tenant_id", 1) or 1)
    return await ApprovalInstanceRepository.find_latest_by_business_key(
        tenant_id=tenant_id,
        scenario_code=QA_PUBLISH_SCENARIO,
        business_key=business_key_for(int(request.id)),
    )


async def sync_after_create(request, question, initiator, approvers: list[Any]) -> ApprovalInstance | None:
    """发完转公开通知后，为仍 pending 的审批人建 instance + task。"""
    try:
        return await _sync_after_create(request, question, initiator, approvers)
    except Exception:
        logger.exception("qa.publish.bridge.create_failed request_id={}", getattr(request, "id", None))
        return None


async def _initiator_display(question, initiator) -> str:
    """发起人写入审批实例的展示名：匿名则为同题别名。"""
    from bisheng.qa_expert.domain.publish_approval_identity import display_name_for_publish_user

    identity = await display_name_for_publish_user(
        question,
        user_id=int(initiator.user_id),
        real_name=str(getattr(initiator, "user_name", "") or ""),
    )
    return identity.display_name


async def _sync_after_create(request, question, initiator, approvers: list[Any]) -> ApprovalInstance | None:
    pending_ids = [int(row.user_id) for row in approvers if str(row.decision) == DECISION_PENDING]
    tenant_id = int(getattr(question, "tenant_id", 1) or 1)
    contract = await ensure_flow_contract(tenant_id)
    expire_at = getattr(request, "expire_at", None)
    payload = {
        "request_id": int(request.id),
        "question_id": int(question.id),
        "expire_at": to_beijing_iso(expire_at) if expire_at else None,
        "duration_days": int(getattr(request, "duration_days", 0) or 0),
    }
    instance = await _get_instance(request)
    if instance is None:
        applicant_display_name = await _initiator_display(question, initiator)
        instance = await ApprovalInstanceRepository.create_instance(
            ApprovalInstance(
                tenant_id=tenant_id,
                scenario_code=QA_PUBLISH_SCENARIO,
                scenario_name=contract.scenario_name,
                handler_key=QA_PUBLISH_SCENARIO,
                business_key=business_key_for(int(request.id)),
                business_resource_type=QA_PUBLISH_BUSINESS_TYPE,
                business_resource_id=str(question.id),
                business_name=str(question.title or ""),
                applicant_user_id=int(initiator.user_id),
                applicant_user_name=applicant_display_name,
                flow_version_id=contract.flow_version_id,
                route_rule_id=contract.route_rule_id,
                status=ApprovalInstanceStatus.PENDING,
                payload_snapshot=payload,
                detail_snapshot={
                    "question_title": str(question.title or ""),
                    "expire_at": payload["expire_at"],
                    "duration_days": payload["duration_days"],
                },
                current_node_name=contract.node_name,
            )
        )
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=tenant_id,
                instance_id=int(instance.id),
                action="submitted",
                operator_user_id=int(initiator.user_id),
                operator_user_name=applicant_display_name,
                detail={"request_id": int(request.id)},
            )
        )
    if not pending_ids:
        await sync_from_publish_request(request, approvers)
        return instance
    existing = await ApprovalInstanceRepository.list_tasks(int(instance.id))
    have = {int(row.approver_user_id) for row in existing}
    new_rows = [
        ApprovalTask(
            tenant_id=tenant_id,
            instance_id=int(instance.id),
            flow_version_id=contract.flow_version_id,
            node_code=contract.node_code,
            node_name=contract.node_name,
            node_order=contract.node_order,
            approver_user_id=uid,
            approver_source_type="resolved",
            node_mode="and",
            status=ApprovalTaskStatus.PENDING,
        )
        for uid in pending_ids
        if uid not in have
    ]
    if new_rows:
        await ApprovalInstanceRepository.create_tasks(new_rows)
    return instance


async def refresh_expire_snapshot(request) -> None:
    """会签截止延后后，把审批实例快照里的 expire_at 对齐 qa_publish_request。"""
    try:
        instance = await _get_instance(request)
        if instance is None:
            return
        expire_iso = to_beijing_iso(getattr(request, "expire_at", None))
        payload = dict(instance.payload_snapshot or {})
        detail = dict(instance.detail_snapshot or {})
        if payload.get("expire_at") == expire_iso and detail.get("expire_at") == expire_iso:
            return
        payload["expire_at"] = expire_iso
        detail["expire_at"] = expire_iso
        instance.payload_snapshot = payload
        instance.detail_snapshot = detail
        await ApprovalInstanceRepository.update_instance(instance)
    except Exception:
        logger.exception("qa.publish.bridge.refresh_expire_failed request_id={}", getattr(request, "id", None))


async def add_pending_task(request, question, user_id: int) -> ApprovalTask | None:
    """中途新增回答专家：补一条 pending 待办。"""
    try:
        instance = await _get_instance(request)
        if instance is None or str(instance.status) != ApprovalInstanceStatus.PENDING:
            initiator = SimpleNamespace(
                user_id=int(getattr(request, "initiator_user_id", 0) or 0),
                user_name="",
            )
            instance = await sync_after_create(request, question, initiator, [])
        if instance is None:
            return None
        tasks = await ApprovalInstanceRepository.list_tasks(int(instance.id))
        for row in tasks:
            if int(row.approver_user_id) == int(user_id):
                return row
        tenant_id = int(getattr(question, "tenant_id", 1) or 1)
        contract = await ensure_flow_contract(tenant_id)
        created = await ApprovalInstanceRepository.create_task(
            ApprovalTask(
                tenant_id=tenant_id,
                instance_id=int(instance.id),
                flow_version_id=contract.flow_version_id,
                node_code=contract.node_code,
                node_name=contract.node_name,
                node_order=contract.node_order,
                approver_user_id=int(user_id),
                approver_source_type="resolved",
                node_mode="and",
                status=ApprovalTaskStatus.PENDING,
            )
        )
        return created
    except Exception:
        logger.exception(
            "qa.publish.bridge.add_task_failed request_id={} user_id={}",
            getattr(request, "id", None),
            user_id,
        )
        return None


async def sync_from_publish_request(request, approvers: list[Any] | None = None) -> None:
    """按 qa_publish_approver 回写 task / instance 状态。"""
    try:
        await _sync_from_publish_request(request, approvers)
    except Exception:
        logger.exception("qa.publish.bridge.sync_failed request_id={}", getattr(request, "id", None))


async def _sync_from_publish_request(request, approvers: list[Any] | None) -> None:
    instance = await _get_instance(request)
    if instance is None:
        return
    if approvers is None:
        from bisheng.qa_expert.domain.repositories import PublishApproverRepository

        approvers = await PublishApproverRepository().list_by_request(int(request.id))
    decision_by_user = {int(row.user_id): str(row.decision) for row in approvers}
    tasks = await ApprovalInstanceRepository.list_tasks(int(instance.id))
    now = now_beijing()
    publish_status = str(request.status)
    for task in tasks:
        wanted = _task_status_for(decision_by_user.get(int(task.approver_user_id), DECISION_PENDING))
        if publish_status != PUBLISH_PENDING and wanted == ApprovalTaskStatus.PENDING:
            wanted = ApprovalTaskStatus.CANCELLED
        if str(task.status) == wanted:
            continue
        task.status = wanted
        if wanted != ApprovalTaskStatus.PENDING:
            task.acted_at = now
        await ApprovalInstanceRepository.update_task(task)
    target = _instance_status_for(publish_status)
    if str(instance.status) != target:
        instance.status = target
        await ApprovalInstanceRepository.update_instance(instance)

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
    ApprovalGateResult,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.database.models.audit_log import AuditLogDao


async def _get_user_role_labels(user_id: int, tenant_id: int) -> frozenset[str]:
    """Return the full set of identity labels for a user.

    Fixed labels (can overlap):
        'admin'        → system super-admin (AdminRole=1)
        'tenant_admin' → tenant admin (via OpenFGA/TenantService)
        'dept_admin'   → department admin (any department)
        'regular_user' → always included for every user (catch-all fallback)

    Dynamic labels (one per system role the user holds):
        'role_{id}'    → user holds the system role with that id
                         e.g. 'role_3', 'role_7'
                         Allows conditions like {"field":"applicant_role","value":"role_3"}

    PRD §4.3: "同一申请人可能同时具备多个身份标签，条件匹配采用'包含即命中'"
    """
    labels: set[str] = {"regular_user"}
    try:
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user_role import UserRoleDao

        user_roles = await UserRoleDao.aget_user_roles(user_id)
        for ur in user_roles:
            if ur.role_id == AdminRole:
                labels.add("admin")
            else:
                labels.add(f"role_{ur.role_id}")
    except Exception:
        pass

    try:
        from bisheng.database.models.department import DepartmentDao

        dept_admins = await DepartmentDao.aget_user_admin_departments(user_id)
        if dept_admins:
            labels.add("dept_admin")
    except Exception:
        pass

    try:
        from bisheng.tenant.domain.services.tenant_service import TenantService

        if await TenantService._is_tenant_admin(user_id, tenant_id):
            labels.add("tenant_admin")
    except Exception:
        pass

    return frozenset(labels)


class ApprovalGate:
    def __init__(
        self,
        *,
        registry: Any,
        scenario_repository: Any = ApprovalScenarioRepository,
        instance_repository: Any = ApprovalInstanceRepository,
        route_matcher: Callable[[list[Any], ApprovalGateRequest], Awaitable[Any | None]] | None = None,
    ) -> None:
        self.registry = registry
        self.scenario_repository = scenario_repository
        self.instance_repository = instance_repository
        self.route_matcher = route_matcher or self._match_first_route

    async def request_or_pass(self, req: ApprovalGateRequest) -> ApprovalGateResult:
        duplicate = await self.instance_repository.find_duplicate_active_instance(
            tenant_id=req.tenant_id,
            scenario_code=req.scenario_code,
            business_key=req.business_key,
            applicant_user_id=req.applicant_user_id,
            active_statuses=req.duplicate_active_statuses,
        )
        if duplicate:
            return ApprovalGateResult(
                decision=self._decision_from_instance_status(duplicate.status),
                instance_id=duplicate.id,
            )

        handler = await self.registry.get_handler(req.scenario_code)
        detail_snapshot = await handler.build_detail(req)
        business_name = await handler.build_title(req)

        scenario = await self.scenario_repository.get_scenario_by_code(req.tenant_id, req.scenario_code)
        if not scenario or not scenario.enabled:
            raise ApprovalScenarioDisabledError()

        route_rules = await self.scenario_repository.list_route_rules(req.tenant_id, scenario.id)
        matched_route = await self.route_matcher(route_rules, req)
        if not matched_route:
            return await self._create_exception_result(
                req=req,
                scenario_name=scenario.scenario_name,
                handler_key=req.scenario_code,
                business_name=business_name,
                detail_snapshot=detail_snapshot,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
            )

        if matched_route.route_type == "pass":
            instance = await self.instance_repository.create_instance(
                ApprovalInstance(
                    tenant_id=req.tenant_id,
                    scenario_code=req.scenario_code,
                    scenario_name=scenario.scenario_name,
                    handler_key=req.scenario_code,
                    business_key=req.business_key,
                    business_resource_type=req.business_resource_type,
                    business_resource_id=req.business_resource_id,
                    business_name=business_name,
                    applicant_user_id=req.applicant_user_id,
                    applicant_user_name=req.applicant_user_name,
                    applicant_department_id=req.applicant_department_id,
                    status=ApprovalInstanceStatus.APPROVED,
                    reason=req.reason,
                    payload_snapshot=req.payload_snapshot,
                    detail_snapshot=detail_snapshot,
                    route_rule_id=getattr(matched_route, "id", None),
                )
            )
            # PASS route still needs to execute the business handler via outbox
            outbox = await self.instance_repository.create_outbox(
                ApprovalOutbox(
                    tenant_id=req.tenant_id,
                    instance_id=instance.id,
                    handler_key=req.scenario_code,
                    status=ApprovalOutboxStatus.PENDING,
                    payload_snapshot=req.payload_snapshot,
                )
            )
            self._dispatch_outbox_task(outbox.id)
            await AuditLogDao.ainsert_v2(
                tenant_id=req.tenant_id,
                operator_id=0,
                operator_tenant_id=req.tenant_id,
                action="approval.route.pass",
                target_type="approval_instance",
                target_id=str(instance.id),
                reason=getattr(matched_route, "route_name", None),
                metadata={
                    "instance_id": instance.id,
                    "scenario_code": req.scenario_code,
                    "route_id": getattr(matched_route, "id", None),
                    "route_name": getattr(matched_route, "route_name", None),
                    "payload_snapshot": req.payload_snapshot,
                },
                object_name=business_name,
                ip_address=req.ip_address,
            )
            return ApprovalGateResult(decision=ApprovalGateDecision.PASS, instance_id=instance.id)

        flow_version = await self.scenario_repository.get_active_flow_version(
            req.tenant_id,
            matched_route.flow_definition_id,
        )
        if not flow_version:
            return await self._create_exception_result(
                req=req,
                scenario_name=scenario.scenario_name,
                handler_key=req.scenario_code,
                business_name=business_name,
                detail_snapshot=detail_snapshot,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
            )

        node_definitions = await self.scenario_repository.list_node_definitions(req.tenant_id, flow_version.id)
        first_node = node_definitions[0] if node_definitions else None
        approvers = []
        if first_node:
            approvers = await handler.resolve_approvers(first_node.approver_config, req)
        if not first_node or not approvers:
            return await self._create_exception_result(
                req=req,
                scenario_name=scenario.scenario_name,
                handler_key=req.scenario_code,
                business_name=business_name,
                detail_snapshot=detail_snapshot,
                exception_type=ApprovalExceptionType.APPROVER_EMPTY,
                flow_version_id=flow_version.id,
                route_rule_id=getattr(matched_route, "id", None),
                current_node_name=getattr(first_node, "node_name", None),
                node=first_node,
            )

        instance = await self.instance_repository.create_instance(
            ApprovalInstance(
                tenant_id=req.tenant_id,
                scenario_code=req.scenario_code,
                scenario_name=scenario.scenario_name,
                handler_key=req.scenario_code,
                business_key=req.business_key,
                business_resource_type=req.business_resource_type,
                business_resource_id=req.business_resource_id,
                business_name=business_name,
                applicant_user_id=req.applicant_user_id,
                applicant_user_name=req.applicant_user_name,
                applicant_department_id=req.applicant_department_id,
                flow_version_id=flow_version.id,
                route_rule_id=getattr(matched_route, "id", None),
                status=ApprovalInstanceStatus.PENDING,
                reason=req.reason,
                payload_snapshot=req.payload_snapshot,
                detail_snapshot=detail_snapshot,
                current_node_name=first_node.node_name,
            )
        )
        task_ids: list[int] = []
        for approver_user_id in approvers:
            task = await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=req.tenant_id,
                    instance_id=instance.id,
                    flow_version_id=flow_version.id,
                    node_code=first_node.node_code,
                    node_name=first_node.node_name,
                    node_order=first_node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type="resolved",
                    node_mode=first_node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )
            task_ids.append(task.id)
        await self.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=req.tenant_id,
                instance_id=instance.id,
                action="submitted",
                operator_user_id=req.applicant_user_id,
                operator_user_name=req.applicant_user_name,
                detail={},
            )
        )
        await AuditLogDao.ainsert_v2(
            tenant_id=req.tenant_id,
            operator_id=req.applicant_user_id,
            operator_tenant_id=req.tenant_id,
            action="approval.request.submit",
            target_type="approval_instance",
            target_id=str(instance.id),
            reason=req.reason,
            metadata={
                "instance_id": instance.id,
                "scenario_code": req.scenario_code,
                "handler": req.scenario_code,
                "payload_snapshot": req.payload_snapshot,
                "business_resource_type": req.business_resource_type,
                "business_resource_id": req.business_resource_id,
            },
            operator_name=req.applicant_user_name,
            object_name=business_name,
            ip_address=req.ip_address,
        )
        return ApprovalGateResult(
            decision=ApprovalGateDecision.PENDING,
            instance_id=instance.id,
            task_ids=task_ids,
        )

    async def _create_exception_result(
        self,
        *,
        req: ApprovalGateRequest,
        scenario_name: str,
        handler_key: str,
        business_name: str,
        detail_snapshot: dict[str, Any],
        exception_type: str,
        flow_version_id: int | None = None,
        route_rule_id: int | None = None,
        current_node_name: str | None = None,
        node=None,
    ) -> ApprovalGateResult:
        status = ApprovalInstanceStatus.EXCEPTION
        if exception_type == ApprovalExceptionType.EXECUTE_FAILED:
            status = ApprovalInstanceStatus.EXECUTE_FAILED
        instance = await self.instance_repository.create_instance(
            ApprovalInstance(
                tenant_id=req.tenant_id,
                scenario_code=req.scenario_code,
                scenario_name=scenario_name,
                handler_key=handler_key,
                business_key=req.business_key,
                business_resource_type=req.business_resource_type,
                business_resource_id=req.business_resource_id,
                business_name=business_name,
                applicant_user_id=req.applicant_user_id,
                applicant_user_name=req.applicant_user_name,
                applicant_department_id=req.applicant_department_id,
                flow_version_id=flow_version_id,
                route_rule_id=route_rule_id,
                status=status,
                reason=req.reason,
                payload_snapshot=req.payload_snapshot,
                detail_snapshot=detail_snapshot,
                current_node_name=current_node_name,
            )
        )
        exception_detail: dict[str, Any] = {
            "scenario_code": req.scenario_code,
            "business_key": req.business_key,
            "current_node_name": current_node_name,
        }
        if node is not None:
            exception_detail.update(
                {
                    "node_code": getattr(node, "node_code", None),
                    "node_name": getattr(node, "node_name", None),
                    "node_order": getattr(node, "node_order", None),
                    "node_mode": getattr(node, "node_mode", None),
                }
            )
        await self.instance_repository.create_exception(
            ApprovalException(
                tenant_id=req.tenant_id,
                instance_id=instance.id,
                exception_type=exception_type,
                detail=exception_detail,
            )
        )
        # Audit the submission even when the instance lands in exception state — every
        # instance creation must leave a trace per the approval module compliance rule.
        await AuditLogDao.ainsert_v2(
            tenant_id=req.tenant_id,
            operator_id=req.applicant_user_id,
            operator_tenant_id=req.tenant_id,
            action="approval.request.submit",
            target_type="approval_instance",
            target_id=str(instance.id),
            reason=req.reason,
            metadata={
                "instance_id": instance.id,
                "scenario_code": req.scenario_code,
                "handler": handler_key,
                "payload_snapshot": req.payload_snapshot,
                "business_resource_type": req.business_resource_type,
                "business_resource_id": req.business_resource_id,
                "instance_status": status,
                "exception_type": exception_type,
                "flow_version_id": flow_version_id,
                "route_rule_id": route_rule_id,
                "current_node_name": current_node_name,
            },
            operator_name=req.applicant_user_name,
            object_name=business_name,
            ip_address=req.ip_address,
        )
        # Notify tenant admins so they can handle the exception
        await self._notify_admins_of_exception(
            tenant_id=req.tenant_id,
            applicant_user_id=req.applicant_user_id,
            exception_type=exception_type,
            business_name=instance.business_name,
            instance_id=instance.id,
        )
        return ApprovalGateResult(
            decision=ApprovalGateDecision.EXCEPTION,
            instance_id=instance.id,
            exception_type=exception_type,
        )

    @staticmethod
    def _dispatch_outbox_task(outbox_id: int) -> None:
        try:
            from bisheng.worker.approval.tasks import execute_approval_outbox

            execute_approval_outbox.delay(outbox_id)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("failed to dispatch approval outbox task: outbox_id=%s", outbox_id)

    @staticmethod
    async def _notify_admins_of_exception(
        *,
        tenant_id: int,
        applicant_user_id: int,
        exception_type: str,
        business_name: str,
        instance_id: int,
    ) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_admins(
            tenant_id=tenant_id,
            applicant_user_id=applicant_user_id,
            action_code=f"approval_exception_{exception_type}",
            business_name=business_name,
            instance_id=instance_id,
        )

    async def _match_first_route(self, route_rules: list[Any], req: ApprovalGateRequest) -> Any | None:
        """Evaluate route conditions top-to-bottom; return the first matching enabled route.

        match_config format (stored on ApprovalRouteRule):
          {}                              → catch-all (no condition), always matches
          {"field": "applicant_role",
           "value": "admin"}             → matches if 'admin' ∈ user's identity labels
          {"field": "<payload_key>",
           "value": "<expected>"}        → matches if payload_snapshot[field] == expected

        applicant_role condition uses "包含即命中" semantics:
          a user may have multiple labels simultaneously (e.g. admin + dept_admin).
          The condition matches if the user has AT LEAST the specified label.

        Supported applicant_role values:
          "admin"        → 系统管理员 (AdminRole=1)
          "tenant_admin" → 租户管理员
          "dept_admin"   → 部门管理员
          "regular_user" → 普通用户 (catch-all, every user has this label)
        """
        user_labels: frozenset[str] | None = None  # lazily resolved; shared across routes

        for route in route_rules:
            if not getattr(route, "enabled", True):
                continue
            match_config = getattr(route, "match_config", {}) or {}
            field = match_config.get("field", "")
            if not field:
                return route  # catch-all branch

            expected = str(match_config.get("value", ""))

            if field == "applicant_role":
                if user_labels is None:
                    user_labels = await _get_user_role_labels(req.applicant_user_id, req.tenant_id)
                if expected in user_labels:
                    return route
            elif field == "applicant_department_id":
                dept_id = req.applicant_department_id
                if dept_id is not None and str(dept_id) == expected:
                    return route
            else:
                # Payload-based condition: compare against payload_snapshot field
                payload_val = req.payload_snapshot.get(field)
                if payload_val is not None and str(payload_val) == expected:
                    return route

        return None

    @staticmethod
    def _decision_from_instance_status(status: str) -> ApprovalGateDecision:
        if status == ApprovalInstanceStatus.EXCEPTION:
            return ApprovalGateDecision.EXCEPTION
        return ApprovalGateDecision.PENDING

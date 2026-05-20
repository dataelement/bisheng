from __future__ import annotations

from typing import Any, Awaitable, Callable

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
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

        if matched_route.route_type == 'pass':
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
                    status=ApprovalInstanceStatus.EXECUTED,
                    reason=req.reason,
                    payload_snapshot=req.payload_snapshot,
                    detail_snapshot=detail_snapshot,
                    route_rule_id=getattr(matched_route, 'id', None),
                )
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
                route_rule_id=getattr(matched_route, 'id', None),
                current_node_name=getattr(first_node, 'node_name', None),
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
                route_rule_id=getattr(matched_route, 'id', None),
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
                    approver_source_type='resolved',
                    node_mode=first_node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )
            task_ids.append(task.id)
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
        await self.instance_repository.create_exception(
            ApprovalException(
                tenant_id=req.tenant_id,
                instance_id=instance.id,
                exception_type=exception_type,
                detail={
                    'scenario_code': req.scenario_code,
                    'business_key': req.business_key,
                    'current_node_name': current_node_name,
                },
            )
        )
        return ApprovalGateResult(
            decision=ApprovalGateDecision.EXCEPTION,
            instance_id=instance.id,
            exception_type=exception_type,
        )

    @staticmethod
    async def _match_first_route(route_rules: list[Any], _req: ApprovalGateRequest) -> Any | None:
        return route_rules[0] if route_rules else None

    @staticmethod
    def _decision_from_instance_status(status: str) -> ApprovalGateDecision:
        if status == ApprovalInstanceStatus.EXCEPTION:
            return ApprovalGateDecision.EXCEPTION
        return ApprovalGateDecision.PENDING

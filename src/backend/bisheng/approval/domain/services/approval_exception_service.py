from __future__ import annotations

import logging
from typing import Any

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import ApprovalNodeDefinition, ApprovalRouteRule
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.database.models.audit_log import AuditLogDao

logger = logging.getLogger(__name__)


class ApprovalExceptionService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    @classmethod
    async def retry_exception_api(
        cls,
        *,
        exception_id: int,
        action: str,
        operator_user_id: int,
        approver_user_ids: list[int] | None = None,
        ip_address: str | None = None,
    ):
        service = cls(instance_repository=ApprovalInstanceRepository)
        exception = await service._get_exception(exception_id)
        instance = await service._get_instance(exception.instance_id)

        if action == "skip_node":
            await service.skip_node(exception_id=exception_id, resolved_by_user_id=operator_user_id)
            await service._write_audit_log(
                action="approval.exception.skip_node",
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
                ip_address=ip_address,
            )
            return {"exception_id": exception_id, "instance_id": instance.id, "status": "resolved"}

        if action == "assign_approvers":
            if not approver_user_ids:
                raise ValueError("approver_user_ids required for assign_approvers")
            existing_task_ids = {t.id for t in await service.instance_repository.list_tasks(instance.id)}
            await service.assign_approvers(
                exception_id=exception_id,
                approver_user_ids=approver_user_ids,
                resolved_by_user_id=operator_user_id,
            )
            new_task_ids = [
                t.id for t in await service.instance_repository.list_tasks(instance.id) if t.id not in existing_task_ids
            ]
            await service._write_audit_log(
                action="approval.exception.assign_approver",
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
                extra={
                    "approver_user_ids": approver_user_ids,
                    "task_ids": new_task_ids,
                },
                ip_address=ip_address,
            )
            return {"exception_id": exception_id, "instance_id": instance.id, "status": "resolved"}

        if action == "mark_manually_completed":
            await service.mark_manually_completed(
                exception_id=exception_id,
                resolved_by_user_id=operator_user_id,
            )
            await service._write_audit_log(
                action="approval.exception.retry",
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
                ip_address=ip_address,
            )
            return {"exception_id": exception_id, "instance_id": instance.id, "status": "resolved"}

        if action != "retry":
            raise ValueError(f"unsupported exception action: {action}")

        if exception.exception_type == "execute_failed":
            retried = await service.retry_execute_failed_api(
                exception_id=exception_id,
                resolved_by_user_id=operator_user_id,
                scenario_code=instance.scenario_code,
            )
            await service._write_audit_log(
                action="approval.exception.retry",
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
                ip_address=ip_address,
            )
            return {
                "exception_id": exception_id,
                "instance_id": instance.id,
                "status": "resolved" if retried else "open",
            }

        if exception.exception_type == "route_missing":
            await service._retry_route_missing(exception, instance, operator_user_id)
        elif exception.exception_type == "approver_empty":
            from bisheng.common.errcode.approval import ApprovalApproverEmptyError

            route_rule, flow_version_id, node = await service._resolve_retry_route(instance)
            handler = await service._build_handler(instance.scenario_code)
            req = service._build_gate_request(instance)
            approver_user_ids = await handler.resolve_approvers(getattr(node, "approver_config", {}) or {}, req)
            if not approver_user_ids:
                raise ApprovalApproverEmptyError()
            await service.assign_approvers(
                exception_id=exception_id,
                approver_user_ids=approver_user_ids,
                resolved_by_user_id=operator_user_id,
                node=node,
            )
        else:
            raise ValueError(f"unsupported exception type: {exception.exception_type}")

        await service._write_audit_log(
            action="approval.exception.retry",
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            exception_id=exception_id,
            instance_id=instance.id,
            exception_type=exception.exception_type,
            ip_address=ip_address,
        )
        return {"exception_id": exception_id, "instance_id": instance.id, "status": "resolved"}

    @classmethod
    async def cancel_exception_api(
        cls,
        *,
        exception_id: int,
        operator_user_id: int,
        reason: str,
        ip_address: str | None = None,
    ):
        if not reason or not reason.strip():
            raise ValueError("cancel reason is required")
        service = cls(instance_repository=ApprovalInstanceRepository)
        exception = await service._get_exception(exception_id)
        instance = await service._get_instance(exception.instance_id)

        # Cancel all pending tasks
        tasks = await service.instance_repository.list_tasks(instance.id)
        for task in tasks:
            if task.status == ApprovalTaskStatus.PENDING:
                task.status = ApprovalTaskStatus.CANCELLED
                await service.instance_repository.update_task(task)

        instance.status = ApprovalInstanceStatus.CANCELLED
        await service.instance_repository.update_instance(instance)
        operator_user_name = await service._lookup_user_name(operator_user_id)
        await service.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action="cancelled",
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={"reason": reason.strip(), "exception_id": exception_id},
            )
        )
        exception.status = "resolved"
        exception.resolved_by_user_id = operator_user_id
        exception.resolved_action = "cancel"
        await service.instance_repository.update_exception(exception)
        await service._write_audit_log(
            action="approval.exception.cancel",
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            exception_id=exception_id,
            instance_id=instance.id,
            exception_type=exception.exception_type,
            reason=reason.strip(),
            ip_address=ip_address,
        )
        # Reset business-side membership so the applicant can re-apply
        try:
            handler = await service._build_handler(instance.scenario_code)
            on_cancelled = getattr(handler, "on_cancelled", None)
            if callable(on_cancelled):
                await on_cancelled(instance.id, instance.payload_snapshot or {}, reason.strip())
        except Exception:
            logger.exception("cancel_exception: on_cancelled hook failed for instance %s", instance.id)

        # Notify applicant
        await cls._notify_user(
            sender=operator_user_id,
            receiver_user_id=instance.applicant_user_id,
            action_code="approval_exception_cancelled",
            business_name=instance.business_name,
            instance_id=instance.id,
            reason=reason.strip(),
        )
        return {"exception_id": exception_id, "instance_id": instance.id, "status": "cancelled"}

    async def assign_flow(
        self,
        *,
        exception_id: int,
        flow_version_id: int,
        route_rule_id: int,
        node,
        approver_user_ids: list[int],
        resolved_by_user_id: int,
    ) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        instance.status = ApprovalInstanceStatus.PENDING
        instance.flow_version_id = flow_version_id
        instance.route_rule_id = route_rule_id
        instance.current_node_name = node.node_name
        await self.instance_repository.update_instance(instance)
        created_tasks = await self._create_tasks(
            instance_id=instance.id,
            tenant_id=instance.tenant_id,
            flow_version_id=flow_version_id,
            node=node,
            approver_user_ids=approver_user_ids,
        )
        await self._resolve_exception(exception, resolved_by_user_id, "assign_flow")
        await self._notify_created_tasks(
            sender=instance.applicant_user_id,
            business_name=instance.business_name,
            instance_id=instance.id,
            tasks=created_tasks,
        )

    async def assign_approvers(
        self,
        *,
        exception_id: int,
        approver_user_ids: list[int],
        resolved_by_user_id: int,
        node: Any | None = None,
    ) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        if node is None:
            node = await self._resolve_exception_node(instance, exception)
        created_tasks = await self._create_tasks(
            instance_id=instance.id,
            tenant_id=instance.tenant_id,
            flow_version_id=instance.flow_version_id or 0,
            node=node,
            approver_user_ids=approver_user_ids,
        )
        instance.status = ApprovalInstanceStatus.PENDING
        if node.node_name:
            instance.current_node_name = node.node_name
        await self.instance_repository.update_instance(instance)
        await self._resolve_exception(exception, resolved_by_user_id, "assign_approvers")
        await self._notify_created_tasks(
            sender=instance.applicant_user_id,
            business_name=instance.business_name,
            instance_id=instance.id,
            tasks=created_tasks,
        )

    async def _resolve_exception_node(self, instance, exception):
        """Resolve a node-like object (with node_code/node_name/node_order/node_mode) for the
        exception so downstream task creation never crashes on missing attrs.

        Prefer values from exception.detail; backfill missing fields by looking up node
        definitions from the bound flow_version. Older exception rows may have empty detail
        when the original first_node was None at creation time.
        """
        from types import SimpleNamespace

        detail = exception.detail or {}
        node_code = detail.get("node_code")
        node_name = detail.get("node_name")
        node_order = detail.get("node_order")
        node_mode = detail.get("node_mode")

        if not node_code or not node_name:
            if not instance.flow_version_id:
                raise ValueError(
                    f"cannot resolve approval node: instance has no flow_version_id (instance_id={instance.id})"
                )
            nodes = await ApprovalScenarioRepository.list_node_definitions(
                tenant_id=instance.tenant_id, flow_version_id=instance.flow_version_id
            )
            if not nodes:
                raise ValueError(f"flow version has no nodes: flow_version_id={instance.flow_version_id}")
            target_name = node_name or instance.current_node_name
            matched = (
                next((n for n in nodes if node_code and n.node_code == node_code), None)
                or next((n for n in nodes if target_name and n.node_name == target_name), None)
                or nodes[0]
            )
            node_code = node_code or matched.node_code
            node_name = node_name or matched.node_name
            node_order = node_order if node_order is not None else matched.node_order
            node_mode = node_mode or matched.node_mode

        return SimpleNamespace(
            node_code=node_code,
            node_name=node_name,
            node_order=node_order if node_order is not None else 0,
            node_mode=node_mode or "or",
        )

    @staticmethod
    def _dispatch_outbox(outbox_id: int) -> None:
        try:
            from bisheng.worker.approval.tasks import execute_approval_outbox

            execute_approval_outbox.delay(outbox_id)
        except Exception:
            logger.exception("failed to dispatch approval outbox task: outbox_id=%s", outbox_id)

    async def skip_node(self, *, exception_id: int, resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        detail = exception.detail or {}

        node_code = detail.get("node_code", "")
        node_name = detail.get("node_name", "") or detail.get("current_node_name", "")
        node_order = detail.get("node_order")
        node_mode = detail.get("node_mode", "or")

        # Older exception records may lack node_code/node_order; resolve from node definitions.
        if (node_order is None or not node_code) and instance.flow_version_id and node_name:
            node_defs = await ApprovalScenarioRepository.list_node_definitions(
                instance.tenant_id, instance.flow_version_id
            )
            matched = next((n for n in node_defs if n.node_name == node_name or n.node_code == node_code), None)
            if matched:
                node_code = node_code or matched.node_code
                node_name = matched.node_name
                node_order = matched.node_order
                node_mode = matched.node_mode

        current_node_order = node_order if node_order is not None else 0

        # Create a SKIPPED-status task so the node shows "已跳过" in the progress timeline
        if node_code or node_name:
            from datetime import datetime as _dt

            await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    flow_version_id=instance.flow_version_id or 0,
                    node_code=node_code,
                    node_name=node_name,
                    node_order=current_node_order,
                    approver_user_id=resolved_by_user_id,
                    approver_source_type="skipped",
                    node_mode=node_mode,
                    status=ApprovalTaskStatus.SKIPPED,
                    acted_at=_dt.utcnow(),
                )
            )
        await self._resolve_exception(exception, resolved_by_user_id, "skip_node")
        await self._advance_from_skipped_node(
            instance=instance, current_node_order=current_node_order, operator_user_id=resolved_by_user_id
        )

    async def _advance_from_skipped_node(self, *, instance, current_node_order: int, operator_user_id: int) -> None:
        next_node = None
        if instance.flow_version_id:
            node_defs = await ApprovalScenarioRepository.list_node_definitions(
                instance.tenant_id, instance.flow_version_id
            )
            sorted_nodes = sorted(node_defs, key=lambda n: n.node_order)
            next_node = next((n for n in sorted_nodes if n.node_order > current_node_order), None)

        if next_node is None:
            instance.status = ApprovalInstanceStatus.APPROVED
            instance.current_node_name = None
            await self.instance_repository.update_instance(instance)
            outbox = await self.instance_repository.create_outbox(
                ApprovalOutbox(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    handler_key=instance.handler_key,
                    status=ApprovalOutboxStatus.PENDING,
                    payload_snapshot=instance.payload_snapshot,
                )
            )
            self._dispatch_outbox(outbox.id)
            return

        handler = await self._build_handler(instance.scenario_code)
        from types import SimpleNamespace

        req = SimpleNamespace(
            tenant_id=instance.tenant_id,
            applicant_user_id=instance.applicant_user_id,
            applicant_user_name=instance.applicant_user_name,
            applicant_department_id=instance.applicant_department_id,
            payload_snapshot=instance.payload_snapshot or {},
            business_resource_id=instance.business_resource_id,
            business_resource_type=instance.business_resource_type,
            business_key=instance.business_key,
            business_name=instance.business_name,
            reason=instance.reason,
            scenario_code=instance.scenario_code,
        )
        approvers = await handler.resolve_approvers(next_node.approver_config or {}, req)

        if not approvers:
            from bisheng.approval.domain.models.approval_instance import ApprovalException, ApprovalExceptionType

            instance.status = ApprovalInstanceStatus.EXCEPTION
            instance.current_node_name = next_node.node_name
            await self.instance_repository.update_instance(instance)
            await self.instance_repository.create_exception(
                ApprovalException(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    exception_type=ApprovalExceptionType.APPROVER_EMPTY,
                    detail={
                        "scenario_code": instance.scenario_code,
                        "business_key": instance.business_key,
                        "node_code": next_node.node_code,
                        "node_name": next_node.node_name,
                        "node_order": next_node.node_order,
                        "node_mode": next_node.node_mode,
                    },
                )
            )
            return

        created_tasks = []
        for approver_user_id in approvers:
            created_task = await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    flow_version_id=instance.flow_version_id,
                    node_code=next_node.node_code,
                    node_name=next_node.node_name,
                    node_order=next_node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type="resolved",
                    node_mode=next_node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )
            created_tasks.append(created_task)

        instance.status = ApprovalInstanceStatus.PENDING
        instance.current_node_name = next_node.node_name
        await self.instance_repository.update_instance(instance)

        # Notify the new approvers that they have a pending task
        for task in created_tasks:
            await self._notify_user(
                sender=operator_user_id,
                receiver_user_id=task.approver_user_id,
                action_code="approval_task_pending",
                business_name=instance.business_name or "",
                instance_id=instance.id,
                task_id=task.id,
            )

    async def retry_execute_failed(
        self,
        *,
        exception_id: int,
        resolved_by_user_id: int,
        executor,
    ) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        success = executor(instance.id)
        if success:
            instance.status = ApprovalInstanceStatus.EXECUTED
            await self.instance_repository.update_instance(instance)
            await self._resolve_exception(exception, resolved_by_user_id, "retry_execute_failed")

    async def retry_execute_failed_api(
        self,
        *,
        exception_id: int,
        resolved_by_user_id: int,
        scenario_code: str,
    ) -> bool:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        outboxes = await self.instance_repository.list_outbox(instance.id)
        if not outboxes:
            raise ValueError(f"outbox not found for instance: {instance.id}")
        outbox = outboxes[-1]
        handler = await self._build_handler(scenario_code)
        try:
            await handler.on_approved(instance.id, outbox.payload_snapshot)
        except Exception as exc:  # noqa: BLE001
            outbox.status = ApprovalOutboxStatus.FAILED
            outbox.retry_count += 1
            outbox.error_summary = str(exc)
            await self.instance_repository.update_outbox(outbox)
            return False

        outbox.status = ApprovalOutboxStatus.SUCCESS
        outbox.error_summary = None
        await self.instance_repository.update_outbox(outbox)
        instance.status = ApprovalInstanceStatus.EXECUTED
        await self.instance_repository.update_instance(instance)
        await self._resolve_exception(exception, resolved_by_user_id, "retry_execute_failed")
        return True

    async def _create_tasks(
        self, *, instance_id: int, tenant_id: int, flow_version_id: int, node, approver_user_ids: list[int]
    ) -> list[ApprovalTask]:
        created_tasks = []
        for approver_user_id in approver_user_ids:
            created_task = await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    flow_version_id=flow_version_id,
                    node_code=node.node_code,
                    node_name=node.node_name,
                    node_order=node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type="manual_assign",
                    node_mode=node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )
            created_tasks.append(created_task)
        return created_tasks

    async def _notify_created_tasks(
        self,
        *,
        sender: int,
        business_name: str,
        instance_id: int,
        tasks: list[ApprovalTask],
    ) -> None:
        for task in tasks:
            await self._notify_user(
                sender=sender,
                receiver_user_id=task.approver_user_id,
                action_code="approval_task_pending",
                business_name=business_name or "",
                instance_id=instance_id,
                task_id=task.id,
            )

    async def mark_manually_completed(self, *, exception_id: int, resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        if exception.exception_type != "execute_failed":
            raise ValueError("mark_manually_completed only applies to execute_failed exceptions")
        instance.status = ApprovalInstanceStatus.EXECUTED
        await self.instance_repository.update_instance(instance)
        await self._resolve_exception(exception, resolved_by_user_id, "mark_manually_completed")

    async def _resolve_exception(self, exception, resolved_by_user_id: int, resolved_action: str) -> None:
        exception.status = "resolved"
        exception.resolved_by_user_id = resolved_by_user_id
        exception.resolved_action = resolved_action
        await self.instance_repository.update_exception(exception)
        instance = await self._get_instance(exception.instance_id)
        operator_user_name = await self._lookup_user_name(resolved_by_user_id)
        await self.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action=resolved_action,
                operator_user_id=resolved_by_user_id,
                operator_user_name=operator_user_name,
                detail={"exception_id": exception.id, "exception_type": exception.exception_type},
            )
        )

    @staticmethod
    async def _lookup_user_name(user_id: int | None) -> str | None:
        if not user_id:
            return None
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(user_id)
        return user.user_name if user else None

    async def _get_exception(self, exception_id: int):
        exception = await self.instance_repository.get_exception(exception_id)
        if exception is None:
            raise ValueError(f"exception not found: {exception_id}")
        return exception

    async def _get_instance(self, instance_id: int):
        instance = await self.instance_repository.get_instance(instance_id)
        if instance is None:
            raise ValueError(f"instance not found: {instance_id}")
        return instance

    async def _retry_route_missing(self, exception, instance, operator_user_id: int) -> None:
        """Re-run the full gate route-matching logic for a route_missing exception.

        Handles both 'pass' and 'flow' route types and respects match conditions,
        so that the admin's newly configured route is picked up correctly.
        """
        from bisheng.approval.domain.models.approval_instance import ApprovalOutbox, ApprovalOutboxStatus
        from bisheng.approval.domain.services.approval_gate import ApprovalGate
        from bisheng.common.errcode.approval import (
            ApprovalApproverEmptyError,
            ApprovalRetryNoActiveFlowVersionError,
            ApprovalRetryNoFlowNodesError,
            ApprovalRetryNoFlowRouteError,
        )

        scenario = await ApprovalScenarioRepository.get_scenario_by_code(instance.tenant_id, instance.scenario_code)
        if scenario is None or not scenario.enabled:
            raise ValueError(f"scenario not enabled: {instance.scenario_code}")

        route_rules = await ApprovalScenarioRepository.list_route_rules(instance.tenant_id, scenario.id)
        req = self._build_gate_request(instance)

        # Re-run full condition matching (respects enabled flag and match_config)
        _gate = ApprovalGate(registry=None)
        matched_route = await _gate._match_first_route(route_rules, req)
        if matched_route is None:
            raise ApprovalRetryNoFlowRouteError()

        if matched_route.route_type == "pass":
            # Direct-pass route: mark instance approved and dispatch business handler
            instance.status = ApprovalInstanceStatus.APPROVED
            instance.route_rule_id = matched_route.id
            await self.instance_repository.update_instance(instance)
            outbox = await self.instance_repository.create_outbox(
                ApprovalOutbox(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    handler_key=instance.handler_key,
                    status=ApprovalOutboxStatus.PENDING,
                    payload_snapshot=instance.payload_snapshot,
                )
            )
            ApprovalGate._dispatch_outbox_task(outbox.id)
            await self._resolve_exception(exception, operator_user_id, "assign_flow")
            return

        if matched_route.flow_definition_id is None:
            raise ApprovalRetryNoFlowRouteError()

        flow_version = await ApprovalScenarioRepository.get_active_flow_version(
            instance.tenant_id, matched_route.flow_definition_id
        )
        if flow_version is None:
            raise ApprovalRetryNoActiveFlowVersionError()

        node_definitions = await ApprovalScenarioRepository.list_node_definitions(instance.tenant_id, flow_version.id)
        if not node_definitions:
            raise ApprovalRetryNoFlowNodesError()

        handler = await self._build_handler(instance.scenario_code)
        first_node = node_definitions[0]
        approver_user_ids = await handler.resolve_approvers(first_node.approver_config or {}, req)
        if not approver_user_ids:
            raise ApprovalApproverEmptyError()

        await self.assign_flow(
            exception_id=exception.id,
            flow_version_id=flow_version.id,
            route_rule_id=matched_route.id,
            node=first_node,
            approver_user_ids=approver_user_ids,
            resolved_by_user_id=operator_user_id,
        )

    async def _resolve_retry_route(self, instance) -> tuple[ApprovalRouteRule, int, ApprovalNodeDefinition]:
        scenario = await ApprovalScenarioRepository.get_scenario_by_code(instance.tenant_id, instance.scenario_code)
        if scenario is None or not scenario.enabled:
            raise ValueError(f"scenario not enabled: {instance.scenario_code}")

        route_rules = await ApprovalScenarioRepository.list_route_rules(instance.tenant_id, scenario.id)
        from bisheng.common.errcode.approval import (
            ApprovalRetryNoActiveFlowVersionError,
            ApprovalRetryNoFlowNodesError,
            ApprovalRetryNoFlowRouteError,
        )

        route_rule = next(
            (row for row in route_rules if row.route_type == "flow" and getattr(row, "enabled", True)),
            None,
        )
        if route_rule is None or route_rule.flow_definition_id is None:
            raise ApprovalRetryNoFlowRouteError()

        flow_version = await ApprovalScenarioRepository.get_active_flow_version(
            instance.tenant_id,
            route_rule.flow_definition_id,
        )
        if flow_version is None:
            raise ApprovalRetryNoActiveFlowVersionError()

        node_definitions = await ApprovalScenarioRepository.list_node_definitions(instance.tenant_id, flow_version.id)
        if not node_definitions:
            raise ApprovalRetryNoFlowNodesError()
        return route_rule, flow_version.id, node_definitions[0]

    @staticmethod
    def _build_gate_request(instance) -> ApprovalGateRequest:
        return ApprovalGateRequest(
            tenant_id=instance.tenant_id,
            scenario_code=instance.scenario_code,
            business_key=instance.business_key,
            business_resource_type=instance.business_resource_type,
            business_resource_id=instance.business_resource_id,
            business_name=instance.business_name,
            applicant_user_id=instance.applicant_user_id,
            applicant_user_name=instance.applicant_user_name,
            applicant_department_id=instance.applicant_department_id,
            reason=instance.reason,
            payload_snapshot=instance.payload_snapshot or {},
            detail_snapshot=instance.detail_snapshot or {},
        )

    async def _build_handler(self, scenario_code: str) -> Any:
        return await build_runtime_handler(scenario_code)

    @staticmethod
    async def _notify_user(
        *,
        sender: int,
        receiver_user_id: int,
        action_code: str,
        business_name: str,
        instance_id: int,
        reason: str | None = None,
        task_id: int | None = None,
    ) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_user(
            sender=sender,
            receiver_user_id=receiver_user_id,
            action_code=action_code,
            business_name=business_name,
            instance_id=instance_id,
            reason=reason,
            task_id=task_id,
        )

    @staticmethod
    async def _write_audit_log(
        *,
        action: str,
        tenant_id: int,
        operator_user_id: int,
        operator_tenant_id: int,
        exception_id: int,
        instance_id: int,
        exception_type: str,
        reason: str | None = None,
        extra: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "instance_id": instance_id,
            "exception_type": exception_type,
        }
        # Enrich with handler/retry_count/payload_snapshot from the live records
        # so audit rows carry the full context PRD §9.1 expects.
        try:
            instance = await ApprovalInstanceRepository.get_instance(instance_id)
            if instance is not None:
                metadata["handler"] = instance.handler_key or instance.scenario_code
                if action == "approval.exception.cancel":
                    metadata["payload_snapshot"] = instance.payload_snapshot
        except Exception:
            logger.exception("audit metadata enrichment failed: instance_id=%s", instance_id)
        if action == "approval.exception.retry":
            try:
                outboxes = await ApprovalInstanceRepository.list_outbox(instance_id)
                if outboxes:
                    metadata["retry_count"] = outboxes[-1].retry_count
            except Exception:
                logger.exception("audit retry_count lookup failed: instance_id=%s", instance_id)
        if extra:
            metadata.update(extra)
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator_user_id,
            operator_tenant_id=operator_tenant_id,
            action=action,
            target_type="approval_exception",
            target_id=str(exception_id),
            reason=reason,
            metadata=metadata,
            ip_address=ip_address,
        )

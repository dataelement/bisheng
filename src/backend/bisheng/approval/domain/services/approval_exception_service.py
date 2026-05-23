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
    ):
        service = cls(instance_repository=ApprovalInstanceRepository)
        exception = await service._get_exception(exception_id)
        instance = await service._get_instance(exception.instance_id)

        if action == 'skip_node':
            await service.skip_node(exception_id=exception_id, resolved_by_user_id=operator_user_id)
            await service._write_audit_log(
                action='approval.exception.skip_node',
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
            )
            return {'exception_id': exception_id, 'instance_id': instance.id, 'status': 'resolved'}

        if action == 'assign_approvers':
            if not approver_user_ids:
                raise ValueError('approver_user_ids required for assign_approvers')
            await service.assign_approvers(
                exception_id=exception_id,
                approver_user_ids=approver_user_ids,
                resolved_by_user_id=operator_user_id,
            )
            await service._write_audit_log(
                action='approval.exception.assign_approver',
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
                extra={'approver_user_ids': approver_user_ids},
            )
            return {'exception_id': exception_id, 'instance_id': instance.id, 'status': 'resolved'}

        if action == 'mark_manually_completed':
            await service.mark_manually_completed(
                exception_id=exception_id,
                resolved_by_user_id=operator_user_id,
            )
            await service._write_audit_log(
                action='approval.exception.retry',
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
            )
            return {'exception_id': exception_id, 'instance_id': instance.id, 'status': 'resolved'}

        if action != 'retry':
            raise ValueError(f'unsupported exception action: {action}')

        if exception.exception_type == 'execute_failed':
            retried = await service.retry_execute_failed_api(
                exception_id=exception_id,
                resolved_by_user_id=operator_user_id,
                scenario_code=instance.scenario_code,
            )
            await service._write_audit_log(
                action='approval.exception.retry',
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                exception_id=exception_id,
                instance_id=instance.id,
                exception_type=exception.exception_type,
            )
            return {
                'exception_id': exception_id,
                'instance_id': instance.id,
                'status': 'resolved' if retried else 'open',
            }

        route_rule, flow_version_id, node = await service._resolve_retry_route(instance)
        handler = await service._build_handler(instance.scenario_code)
        req = service._build_gate_request(instance)

        approver_user_ids = await handler.resolve_approvers(getattr(node, 'approver_config', {}) or {}, req)
        if not approver_user_ids:
            raise ValueError(f'no approvers resolved for exception {exception_id}')

        if exception.exception_type == 'route_missing':
            await service.assign_flow(
                exception_id=exception_id,
                flow_version_id=flow_version_id,
                route_rule_id=route_rule.id,
                node=node,
                approver_user_ids=approver_user_ids,
                resolved_by_user_id=operator_user_id,
            )
        elif exception.exception_type == 'approver_empty':
            await service.assign_approvers(
                exception_id=exception_id,
                approver_user_ids=approver_user_ids,
                resolved_by_user_id=operator_user_id,
            )
        else:
            raise ValueError(f'unsupported exception type: {exception.exception_type}')

        await service._write_audit_log(
            action='approval.exception.retry',
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            exception_id=exception_id,
            instance_id=instance.id,
            exception_type=exception.exception_type,
        )
        return {'exception_id': exception_id, 'instance_id': instance.id, 'status': 'resolved'}

    @classmethod
    async def cancel_exception_api(
        cls,
        *,
        exception_id: int,
        operator_user_id: int,
        reason: str,
    ):
        if not reason or not reason.strip():
            raise ValueError('cancel reason is required')
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
        instance.reason = reason.strip()
        await service.instance_repository.update_instance(instance)
        await service.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action='cancelled',
                operator_user_id=operator_user_id,
                detail={'reason': reason.strip(), 'exception_id': exception_id},
            )
        )
        exception.status = 'resolved'
        exception.resolved_by_user_id = operator_user_id
        exception.resolved_action = 'cancel'
        await service.instance_repository.update_exception(exception)
        await service._write_audit_log(
            action='approval.exception.cancel',
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            exception_id=exception_id,
            instance_id=instance.id,
            exception_type=exception.exception_type,
            reason=reason.strip(),
        )
        # Notify applicant
        await cls._notify_user(
            sender=operator_user_id,
            receiver_user_id=instance.applicant_user_id,
            action_code='approval_exception_cancelled',
            business_name=instance.business_name,
            instance_id=instance.id,
        )
        return {'exception_id': exception_id, 'instance_id': instance.id, 'status': 'cancelled'}

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
        await self._create_tasks(instance_id=instance.id, tenant_id=instance.tenant_id, flow_version_id=flow_version_id, node=node, approver_user_ids=approver_user_ids)
        await self._resolve_exception(exception, resolved_by_user_id, 'assign_flow')

    async def assign_approvers(self, *, exception_id: int, approver_user_ids: list[int], resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        detail = exception.detail or {}
        node = type('Node', (), detail)()
        await self._create_tasks(
            instance_id=instance.id,
            tenant_id=instance.tenant_id,
            flow_version_id=instance.flow_version_id or 0,
            node=node,
            approver_user_ids=approver_user_ids,
        )
        instance.status = ApprovalInstanceStatus.PENDING
        await self.instance_repository.update_instance(instance)
        await self._resolve_exception(exception, resolved_by_user_id, 'assign_approvers')

    @staticmethod
    def _dispatch_outbox(outbox_id: int) -> None:
        try:
            from bisheng.worker.approval.tasks import execute_approval_outbox
            execute_approval_outbox.delay(outbox_id)
        except Exception:
            logger.exception('failed to dispatch approval outbox task: outbox_id=%s', outbox_id)

    async def skip_node(self, *, exception_id: int, resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        instance.status = ApprovalInstanceStatus.APPROVED
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
        await self._resolve_exception(exception, resolved_by_user_id, 'skip_node')

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
            await self._resolve_exception(exception, resolved_by_user_id, 'retry_execute_failed')

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
            raise ValueError(f'outbox not found for instance: {instance.id}')
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
        await self._resolve_exception(exception, resolved_by_user_id, 'retry_execute_failed')
        return True

    async def _create_tasks(self, *, instance_id: int, tenant_id: int, flow_version_id: int, node, approver_user_ids: list[int]) -> None:
        for approver_user_id in approver_user_ids:
            await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=tenant_id,
                    instance_id=instance_id,
                    flow_version_id=flow_version_id,
                    node_code=node.node_code,
                    node_name=node.node_name,
                    node_order=node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type='manual_assign',
                    node_mode=node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )

    async def mark_manually_completed(self, *, exception_id: int, resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        if exception.exception_type != 'execute_failed':
            raise ValueError('mark_manually_completed only applies to execute_failed exceptions')
        instance.status = ApprovalInstanceStatus.EXECUTED
        await self.instance_repository.update_instance(instance)
        await self._resolve_exception(exception, resolved_by_user_id, 'mark_manually_completed')

    async def _resolve_exception(self, exception, resolved_by_user_id: int, resolved_action: str) -> None:
        exception.status = 'resolved'
        exception.resolved_by_user_id = resolved_by_user_id
        exception.resolved_action = resolved_action
        await self.instance_repository.update_exception(exception)
        instance = await self._get_instance(exception.instance_id)
        await self.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action=resolved_action,
                operator_user_id=resolved_by_user_id,
                detail={'exception_id': exception.id, 'exception_type': exception.exception_type},
            )
        )

    async def _get_exception(self, exception_id: int):
        exception = await self.instance_repository.get_exception(exception_id)
        if exception is None:
            raise ValueError(f'exception not found: {exception_id}')
        return exception

    async def _get_instance(self, instance_id: int):
        instance = await self.instance_repository.get_instance(instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {instance_id}')
        return instance

    async def _resolve_retry_route(self, instance) -> tuple[ApprovalRouteRule, int, ApprovalNodeDefinition]:
        scenario = await ApprovalScenarioRepository.get_scenario_by_code(instance.tenant_id, instance.scenario_code)
        if scenario is None or not scenario.enabled:
            raise ValueError(f'scenario not enabled: {instance.scenario_code}')

        route_rules = await ApprovalScenarioRepository.list_route_rules(instance.tenant_id, scenario.id)
        from bisheng.common.errcode.approval import (
            ApprovalRetryNoActiveFlowVersionError,
            ApprovalRetryNoFlowNodesError,
            ApprovalRetryNoFlowRouteError,
        )
        route_rule = next(
            (row for row in route_rules if row.route_type == 'flow' and getattr(row, 'enabled', True)),
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
    ) -> None:
        try:
            from bisheng.core.database import get_async_db_session
            from bisheng.message.api.dependencies import get_message_service as _get_message_service
            async with get_async_db_session() as session:
                message_service = await _get_message_service(session)
                content = [
                    {'type': 'system_text', 'content': action_code},
                    {
                        'type': 'business_url',
                        'content': f'--{business_name}',
                        'metadata': {
                            'business_type': 'approval_instance_id',
                            'data': {'approval_instance_id': str(instance_id)},
                        },
                    },
                ]
                await message_service.send_generic_notify(
                    sender=sender,
                    receiver_user_ids=[receiver_user_id],
                    content_item_list=content,
                )
        except Exception:
            logger.exception('failed to send approval notification: action_code=%s', action_code)

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
    ) -> None:
        metadata = {'instance_id': instance_id, 'exception_type': exception_type}
        if extra:
            metadata.update(extra)
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator_user_id,
            operator_tenant_id=operator_tenant_id,
            action=action,
            target_type='approval_exception',
            target_id=str(exception_id),
            reason=reason,
            metadata=metadata,
        )

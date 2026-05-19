from __future__ import annotations

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)


class ApprovalExceptionService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    async def retry_scenario_disabled(
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
        await self._resolve_exception(exception, resolved_by_user_id, 'retry_scenario_disabled')

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

    async def skip_node(self, *, exception_id: int, resolved_by_user_id: int) -> None:
        exception = await self._get_exception(exception_id)
        instance = await self._get_instance(exception.instance_id)
        instance.status = ApprovalInstanceStatus.APPROVED
        await self.instance_repository.update_instance(instance)
        await self.instance_repository.create_outbox(
            ApprovalOutbox(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                handler_key=instance.handler_key,
                status=ApprovalOutboxStatus.PENDING,
                payload_snapshot=instance.payload_snapshot,
            )
        )
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

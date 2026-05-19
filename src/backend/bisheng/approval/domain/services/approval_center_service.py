from __future__ import annotations

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTaskStatus,
)


class ApprovalCenterService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    @classmethod
    async def list_my_tasks(cls, *, tenant_id: int, approver_user_id: int):
        raise NotImplementedError

    @classmethod
    async def get_task_detail(cls, *, task_id: int, login_user):
        raise NotImplementedError

    @classmethod
    async def decide_task_api(cls, *, task_id: int, action: str, operator_user_id: int, operator_user_name: str, comment: str | None = None):
        raise NotImplementedError

    @classmethod
    async def list_my_requests(cls, *, tenant_id: int, applicant_user_id: int):
        raise NotImplementedError

    @classmethod
    async def get_instance_detail(cls, *, instance_id: int, login_user):
        raise NotImplementedError

    @classmethod
    async def withdraw_instance(cls, *, instance_id: int, operator_user_id: int, reason: str | None = None):
        raise NotImplementedError

    @classmethod
    async def resubmit_instance(cls, *, instance_id: int, operator_user_id: int, reason: str | None = None):
        raise NotImplementedError

    async def decide_task(
        self,
        *,
        task_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        comment: str | None = None,
    ) -> None:
        task = await self.instance_repository.get_task(task_id)
        if task is None:
            raise ValueError(f'task not found: {task_id}')
        instance = await self.instance_repository.get_instance(task.instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {task.instance_id}')

        sibling_tasks = await self.instance_repository.list_tasks(instance.id)
        same_node_tasks = [one for one in sibling_tasks if one.node_code == task.node_code]

        if action == 'reject':
            task.status = ApprovalTaskStatus.REJECTED
            task.comment = comment
            await self.instance_repository.update_task(task)
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.CANCELLED
                    await self.instance_repository.update_task(sibling)
            instance.status = ApprovalInstanceStatus.REJECTED
            await self.instance_repository.update_instance(instance)
            await self.instance_repository.create_action_log(
                ApprovalActionLog(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    action='rejected',
                    operator_user_id=operator_user_id,
                    operator_user_name=operator_user_name,
                    detail={'comment': comment},
                )
            )
            return

        task.status = ApprovalTaskStatus.APPROVED
        task.comment = comment
        await self.instance_repository.update_task(task)

        if task.node_mode == 'or':
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.SKIPPED
                    await self.instance_repository.update_task(sibling)
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
            return

        all_same_node_approved = all(one.status == ApprovalTaskStatus.APPROVED for one in same_node_tasks)
        if all_same_node_approved:
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

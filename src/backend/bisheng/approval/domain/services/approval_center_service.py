from __future__ import annotations

from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTaskStatus,
)
from bisheng.common.errcode.approval import ApprovalGrantNotRevokableError
from bisheng.database.models.department import DepartmentDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.services.auth import LoginUser


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

    @classmethod
    async def apply_menu_access_request(
        cls,
        *,
        login_user,
        menu_key: str,
        menu_name: str,
        reason: str | None = None,
    ):
        db_user = await UserDao.aget_user(login_user.user_id)
        is_department_admin = bool(await DepartmentDao.aget_user_admin_departments(login_user.user_id))
        _, web_menu = await LoginUser.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
        menu_approval_mode = await LoginUser.compute_menu_approval_mode(db_user)
        UserMenuAccessService.ensure_application_allowed(
            menu_approval_mode=menu_approval_mode,
            has_menu_access=menu_key in set(web_menu),
        )

        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler('menu_access_request', MenuAccessApprovalHandler())
        gate = ApprovalGate(registry=registry)
        result = await gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=login_user.tenant_id,
                scenario_code='menu_access_request',
                business_key=f'menu:{menu_key}:user:{login_user.user_id}',
                business_resource_type='web_menu',
                business_resource_id=menu_key,
                business_name=menu_name,
                applicant_user_id=login_user.user_id,
                applicant_user_name=login_user.user_name,
                reason=reason,
                payload_snapshot={
                    'menu_key': menu_key,
                    'menu_name': menu_name,
                    'tenant_id': login_user.tenant_id,
                    'applicant_user_id': login_user.user_id,
                },
            )
        )
        return result.model_dump()

    @classmethod
    async def revoke_menu_grant(
        cls,
        *,
        instance_id: int,
        operator_user_id: int,
        reason: str | None = None,
    ):
        instance = await ApprovalInstanceRepository.get_instance(instance_id)
        if instance is None:
            raise ApprovalGrantNotRevokableError()
        menu_key = (instance.payload_snapshot or {}).get('menu_key')
        rows = await UserMenuAccessService.revoke_menu_access(
            tenant_id=instance.tenant_id,
            user_id=instance.applicant_user_id,
            menu_key=menu_key,
            grant_source='approval_instance',
            revoked_by_user_id=operator_user_id,
            revoked_reason=reason,
        )
        if not rows:
            raise ApprovalGrantNotRevokableError()
        return {'revoked_keys': [row.menu_key for row in rows], 'instance_id': instance_id}

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

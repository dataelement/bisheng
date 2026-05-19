from __future__ import annotations

from datetime import datetime

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
from bisheng.common.errcode.approval import ApprovalGrantNotRevokableError
from bisheng.database.models.department import DepartmentDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.services.auth import LoginUser


class _SystemLoginUser:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id

    def is_admin(self) -> bool:
        return True


class ApprovalCenterService:
    def __init__(self, *, instance_repository) -> None:
        self.instance_repository = instance_repository

    @classmethod
    async def list_my_tasks(cls, *, tenant_id: int, approver_user_id: int):
        tasks = await ApprovalQueryRepository.list_tasks_by_approver(tenant_id, approver_user_id)
        data = []
        for task in tasks:
            instance = await ApprovalInstanceRepository.get_instance(task.instance_id)
            data.append(
                {
                    'task_id': task.id,
                    'instance_id': task.instance_id,
                    'scenario_code': instance.scenario_code if instance else None,
                    'business_name': instance.business_name if instance else task.node_name,
                    'status': task.status,
                    'applicant_user_name': instance.applicant_user_name if instance else None,
                    'create_time': task.create_time,
                    'update_time': task.update_time,
                }
            )
        return {'data': data, 'total': len(data)}

    @classmethod
    async def get_task_detail(cls, *, task_id: int, login_user):
        task = await ApprovalInstanceRepository.get_task(task_id)
        if task is None:
            raise ValueError(f'task not found: {task_id}')
        instance = await ApprovalInstanceRepository.get_instance(task.instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {task.instance_id}')
        if not login_user.is_admin() and task.approver_user_id != login_user.user_id and instance.applicant_user_id != login_user.user_id:
            raise PermissionError('task not visible')
        return {
            'task_id': task.id,
            'instance_id': task.instance_id,
            'scenario_code': instance.scenario_code,
            'business_name': instance.business_name,
            'status': task.status,
            'comment': task.comment,
            'detail_snapshot': instance.detail_snapshot,
            'payload_snapshot': instance.payload_snapshot,
            'applicant_user_name': instance.applicant_user_name,
            'create_time': task.create_time,
            'update_time': task.update_time,
        }

    @classmethod
    async def decide_task_api(
        cls,
        *,
        task_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        comment: str | None = None,
    ):
        service = cls(instance_repository=ApprovalInstanceRepository)
        await service.decide_task(
            task_id=task_id,
            action=action,
            operator_user_id=operator_user_id,
            operator_user_name=operator_user_name,
            comment=comment,
        )
        task = await ApprovalInstanceRepository.get_task(task_id)
        instance = await ApprovalInstanceRepository.get_instance(task.instance_id) if task else None
        return {
            'task_id': task.id if task else task_id,
            'instance_id': task.instance_id if task else None,
            'status': task.status if task else None,
            'instance_status': instance.status if instance else None,
            'comment': task.comment if task else comment,
        }

    @classmethod
    async def list_my_requests(cls, *, tenant_id: int, applicant_user_id: int):
        rows = await ApprovalQueryRepository.list_instances_by_applicant(tenant_id, applicant_user_id)
        data = [
            {
                'instance_id': row.id,
                'scenario_code': row.scenario_code,
                'business_name': row.business_name,
                'status': row.status,
                'applicant_user_name': row.applicant_user_name,
                'create_time': row.create_time,
                'update_time': row.update_time,
            }
            for row in rows
        ]
        return {'data': data, 'total': len(data)}

    @classmethod
    async def get_instance_detail(cls, *, instance_id: int, login_user):
        instance = await ApprovalInstanceRepository.get_instance(instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {instance_id}')
        tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        if not login_user.is_admin():
            visible_task_owner = any(task.approver_user_id == login_user.user_id for task in tasks)
            if instance.applicant_user_id != login_user.user_id and not visible_task_owner:
                raise PermissionError('instance not visible')
        action_logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
        return {
            'instance_id': instance.id,
            'scenario_code': instance.scenario_code,
            'business_name': instance.business_name,
            'status': instance.status,
            'reason': instance.reason,
            'payload_snapshot': instance.payload_snapshot,
            'detail_snapshot': instance.detail_snapshot,
            'applicant_user_name': instance.applicant_user_name,
            'create_time': instance.create_time,
            'update_time': instance.update_time,
            'tasks': [
                {
                    'task_id': task.id,
                    'approver_user_id': task.approver_user_id,
                    'node_name': task.node_name,
                    'status': task.status,
                    'comment': task.comment,
                    'update_time': task.update_time,
                }
                for task in tasks
            ],
            'action_logs': [
                {
                    'id': log.id,
                    'action': log.action,
                    'operator_user_id': log.operator_user_id,
                    'operator_user_name': log.operator_user_name,
                    'detail': log.detail,
                    'create_time': log.create_time,
                }
                for log in action_logs
            ],
        }

    @classmethod
    async def withdraw_instance(
        cls,
        *,
        instance_id: int,
        operator_user_id: int,
        operator_user_name: str | None = None,
        reason: str | None = None,
    ):
        instance = await ApprovalInstanceRepository.get_instance(instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {instance_id}')
        if instance.applicant_user_id != operator_user_id:
            raise PermissionError('only applicant can withdraw')
        tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        for task in tasks:
            if task.status == ApprovalTaskStatus.PENDING:
                task.status = ApprovalTaskStatus.CANCELLED
                task.comment = reason
                task.acted_at = datetime.utcnow()
                await ApprovalInstanceRepository.update_task(task)
        instance.status = ApprovalInstanceStatus.WITHDRAWN
        instance.reason = reason or instance.reason
        await ApprovalInstanceRepository.update_instance(instance)
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action='withdrawn',
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={'reason': reason},
            )
        )
        return await cls.get_instance_detail(
            instance_id=instance.id,
            login_user=_SystemLoginUser(operator_user_id),
        )

    @classmethod
    async def resubmit_instance(
        cls,
        *,
        instance_id: int,
        operator_user_id: int,
        operator_user_name: str | None = None,
        reason: str | None = None,
    ):
        instance = await ApprovalInstanceRepository.get_instance(instance_id)
        if instance is None:
            raise ValueError(f'instance not found: {instance_id}')
        if instance.applicant_user_id != operator_user_id:
            raise PermissionError('only applicant can resubmit')
        tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        if not tasks:
            raise ValueError('instance has no tasks to resubmit')
        first_node_order = min(task.node_order for task in tasks)
        first_node_tasks = [task for task in tasks if task.node_order == first_node_order]
        for task in tasks:
            if task.node_order == first_node_order:
                task.status = ApprovalTaskStatus.PENDING
                task.comment = None
                task.acted_at = None
            else:
                task.status = ApprovalTaskStatus.CANCELLED
            await ApprovalInstanceRepository.update_task(task)
        instance.status = ApprovalInstanceStatus.PENDING
        instance.reason = reason or instance.reason
        instance.current_node_name = first_node_tasks[0].node_name if first_node_tasks else instance.current_node_name
        await ApprovalInstanceRepository.update_instance(instance)
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action='resubmitted',
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={'reason': reason},
            )
        )
        return await cls.get_instance_detail(
            instance_id=instance.id,
            login_user=_SystemLoginUser(operator_user_id),
        )

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
            task.acted_at = datetime.utcnow()
            await self.instance_repository.update_task(task)
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.CANCELLED
                    sibling.acted_at = datetime.utcnow()
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
        task.acted_at = datetime.utcnow()
        await self.instance_repository.update_task(task)
        await self.instance_repository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action='approved',
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={'task_id': task.id, 'comment': comment},
            )
        )

        if task.node_mode == 'or':
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.SKIPPED
                    sibling.acted_at = datetime.utcnow()
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

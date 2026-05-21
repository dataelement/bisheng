from __future__ import annotations

from datetime import datetime

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.common.errcode.approval import (
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
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
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.services.auth import LoginUser


class _SystemLoginUser:
    def __init__(self, user_id: int, tenant_id: int = 0) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id

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
            raise ApprovalRequestNotFoundError()
        instance = await ApprovalInstanceRepository.get_instance(task.instance_id)
        if instance is None:
            raise ApprovalRequestNotFoundError()
        if instance.tenant_id != login_user.tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        if not login_user.is_admin() and task.approver_user_id != login_user.user_id and instance.applicant_user_id != login_user.user_id:
            raise ApprovalRequestPermissionDeniedError()
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
        operator_tenant_id: int,
        operator_is_admin: bool = False,
        comment: str | None = None,
    ):
        service = cls(instance_repository=ApprovalInstanceRepository)
        await service.decide_task(
            task_id=task_id,
            action=action,
            operator_user_id=operator_user_id,
            operator_user_name=operator_user_name,
            operator_tenant_id=operator_tenant_id,
            operator_is_admin=operator_is_admin,
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
            raise ApprovalRequestNotFoundError()
        if instance.tenant_id != login_user.tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        if not login_user.is_admin():
            visible_task_owner = any(task.approver_user_id == login_user.user_id for task in tasks)
            if instance.applicant_user_id != login_user.user_id and not visible_task_owner:
                raise ApprovalRequestPermissionDeniedError()
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
        await cls._write_audit_log(
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            action='approval.instance.withdraw',
            target_id=str(instance.id),
            reason=reason,
            metadata={'scenario_code': instance.scenario_code},
            operator_name=operator_user_name,
        )
        return await cls.get_instance_detail(
            instance_id=instance.id,
            login_user=_SystemLoginUser(operator_user_id, tenant_id=instance.tenant_id),
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
            raise ApprovalRequestNotFoundError()
        if instance.applicant_user_id != operator_user_id:
            raise ApprovalRequestPermissionDeniedError()
        if instance.status != ApprovalInstanceStatus.REJECTED:
            raise ApprovalRequestAlreadyProcessedError()

        old_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        if not old_tasks:
            raise ValueError('original instance has no tasks to resubmit from')
        first_node_order = min(t.node_order for t in old_tasks)
        first_node_tasks = [t for t in old_tasks if t.node_order == first_node_order]

        new_instance = await ApprovalInstanceRepository.create_instance(
            ApprovalInstance(
                tenant_id=instance.tenant_id,
                scenario_code=instance.scenario_code,
                scenario_name=instance.scenario_name,
                handler_key=instance.handler_key,
                business_key=instance.business_key,
                business_resource_type=instance.business_resource_type,
                business_resource_id=instance.business_resource_id,
                business_name=instance.business_name,
                applicant_user_id=instance.applicant_user_id,
                applicant_user_name=instance.applicant_user_name,
                applicant_department_id=instance.applicant_department_id,
                flow_version_id=instance.flow_version_id,
                route_rule_id=instance.route_rule_id,
                status=ApprovalInstanceStatus.PENDING,
                reason=reason or instance.reason,
                payload_snapshot=instance.payload_snapshot,
                detail_snapshot=instance.detail_snapshot,
                current_node_name=first_node_tasks[0].node_name if first_node_tasks else None,
            )
        )
        for old_task in first_node_tasks:
            await ApprovalInstanceRepository.create_task(
                ApprovalTask(
                    tenant_id=instance.tenant_id,
                    instance_id=new_instance.id,
                    flow_version_id=old_task.flow_version_id,
                    node_code=old_task.node_code,
                    node_name=old_task.node_name,
                    node_order=old_task.node_order,
                    approver_user_id=old_task.approver_user_id,
                    approver_source_type=old_task.approver_source_type,
                    node_mode=old_task.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=new_instance.tenant_id,
                instance_id=new_instance.id,
                action='resubmitted',
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={'original_instance_id': instance_id, 'reason': reason},
            )
        )
        await cls._write_audit_log(
            tenant_id=new_instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=new_instance.tenant_id,
            action='approval.instance.resubmit',
            target_id=str(new_instance.id),
            reason=reason,
            metadata={'scenario_code': new_instance.scenario_code, 'original_instance_id': instance_id},
            operator_name=operator_user_name,
        )
        return await cls.get_instance_detail(
            instance_id=new_instance.id,
            login_user=_SystemLoginUser(operator_user_id, tenant_id=new_instance.tenant_id),
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
        await cls._write_audit_log(
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            action='approval.menu_access.revoke_grant',
            target_id=str(instance.id),
            reason=reason,
            metadata={
                'scenario_code': instance.scenario_code,
                'menu_key': menu_key,
                'applicant_user_id': instance.applicant_user_id,
            },
        )
        return {'revoked_keys': [row.menu_key for row in rows], 'instance_id': instance_id}

    async def decide_task(
        self,
        *,
        task_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        operator_tenant_id: int,
        operator_is_admin: bool = False,
        comment: str | None = None,
    ) -> None:
        task = await self.instance_repository.get_task(task_id)
        if task is None:
            raise ApprovalRequestNotFoundError()
        instance = await self.instance_repository.get_instance(task.instance_id)
        if instance is None:
            raise ApprovalRequestNotFoundError()
        if instance.tenant_id != operator_tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        if not operator_is_admin and task.approver_user_id != operator_user_id:
            raise ApprovalRequestPermissionDeniedError()
        if task.status != ApprovalTaskStatus.PENDING:
            raise ApprovalRequestAlreadyProcessedError()

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
            await self.__class__._write_audit_log(
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                action='approval.task.reject',
                target_id=str(instance.id),
                reason=comment,
                metadata={'task_id': task.id, 'scenario_code': instance.scenario_code},
                operator_name=operator_user_name,
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
        await self.__class__._write_audit_log(
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            action='approval.task.approve',
            target_id=str(instance.id),
            reason=comment,
            metadata={'task_id': task.id, 'scenario_code': instance.scenario_code},
            operator_name=operator_user_name,
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

    @classmethod
    async def _write_audit_log(
        cls,
        *,
        tenant_id: int,
        operator_user_id: int,
        operator_tenant_id: int,
        action: str,
        target_id: str,
        reason: str | None,
        metadata: dict | None = None,
        operator_name: str | None = None,
    ) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator_user_id,
            operator_tenant_id=operator_tenant_id,
            action=action,
            target_type='approval_instance',
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            operator_name=operator_name,
        )

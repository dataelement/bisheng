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
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
from bisheng.common.errcode.approval import (
    ApprovalGrantNotRevokableError,
    ApprovalRequestAlreadyProcessedError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
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
        if not tasks:
            return {'data': [], 'total': 0}

        instance_ids = list({t.instance_id for t in tasks})
        instances = await ApprovalInstanceRepository.get_instances_by_ids(instance_ids)
        instance_map = {inst.id: inst for inst in instances}

        dept_ids = [inst.applicant_department_id for inst in instances if inst.applicant_department_id]
        dept_name_map: dict[int, str] = {}
        if dept_ids:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_by_ids(list(set(dept_ids)))
            dept_name_map = {d.id: d.name for d in depts}

        # Batch-check which menu_access instances have had their grant revoked
        from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository
        menu_executed_ids = [
            inst.id for inst in instances
            if inst.scenario_code == 'menu_access_request' and inst.status == 'executed'
        ]
        revoked_instance_ids = await UserMenuAccessRepository.get_revoked_instance_ids(menu_executed_ids)

        data = []
        for task in tasks:
            inst = instance_map.get(task.instance_id)
            dept_name = dept_name_map.get(inst.applicant_department_id) if inst and inst.applicant_department_id else None
            data.append({
                'task_id': task.id,
                'instance_id': task.instance_id,
                'scenario_code': inst.scenario_code if inst else None,
                'scenario_name': inst.scenario_name if inst else None,
                'business_name': inst.business_name if inst else task.node_name,
                'status': task.status,
                'instance_status': inst.status if inst else None,
                'grant_revoked': task.instance_id in revoked_instance_ids,
                'current_node_name': task.node_name,
                'applicant_user_name': inst.applicant_user_name if inst else None,
                'applicant_department_id': inst.applicant_department_id if inst else None,
                'applicant_department_name': dept_name,
                'create_time': task.create_time,
                'update_time': task.update_time,
            })
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

        dept_name: str | None = None
        if instance.applicant_department_id:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_by_ids([instance.applicant_department_id])
            if depts:
                dept_name = depts[0].name

        action_logs = await ApprovalInstanceRepository.list_action_logs(instance.id)
        all_tasks = await ApprovalInstanceRepository.list_tasks(instance.id)

        all_task_uids = list({t.approver_user_id for t in all_tasks})
        task_user_name_map: dict[int, str] = {}
        if all_task_uids:
            from bisheng.user.domain.models.user import UserDao
            task_users = await UserDao.aget_user_by_ids(all_task_uids)
            task_user_name_map = {u.user_id: u.user_name for u in (task_users or [])}

        flow_nodes: list = []
        if instance.flow_version_id:
            from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
            node_defs = await ApprovalScenarioRepository.list_node_definitions(
                instance.tenant_id, instance.flow_version_id
            )
            flow_nodes = [
                {
                    'node_code': nd.node_code,
                    'node_name': nd.node_name,
                    'node_order': nd.node_order,
                    'node_mode': nd.node_mode,
                }
                for nd in node_defs
            ]

        grant_revoked = False
        if instance.scenario_code == 'menu_access_request' and instance.status == 'executed':
            from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository
            revoked_ids = await UserMenuAccessRepository.get_revoked_instance_ids([instance.id])
            grant_revoked = instance.id in revoked_ids

        return {
            'task_id': task.id,
            'instance_id': task.instance_id,
            'scenario_code': instance.scenario_code,
            'scenario_name': instance.scenario_name,
            'business_name': instance.business_name,
            'status': task.status,
            'instance_status': instance.status,
            'grant_revoked': grant_revoked,
            'current_node_name': task.node_name,
            'comment': task.comment,
            'detail_snapshot': instance.detail_snapshot,
            'payload_snapshot': instance.payload_snapshot,
            'applicant_user_name': instance.applicant_user_name,
            'applicant_department_id': instance.applicant_department_id,
            'applicant_department_name': dept_name,
            'reason': instance.reason,
            'create_time': instance.create_time,
            'update_time': task.update_time,
            'flow_nodes': flow_nodes,
            'tasks': [
                {
                    'task_id': t.id,
                    'approver_user_id': t.approver_user_id,
                    'approver_user_name': task_user_name_map.get(t.approver_user_id),
                    'node_name': t.node_name,
                    'node_order': t.node_order,
                    'node_mode': t.node_mode,
                    'status': t.status,
                    'comment': t.comment,
                    'update_time': t.update_time,
                }
                for t in all_tasks
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
        ip_address: str | None = None,
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
            ip_address=ip_address,
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
    async def _enrich_with_approver_and_dept(
        cls,
        instance_ids: list[int],
        dept_ids: list[int],
    ) -> tuple[dict[int, str], dict[int, str]]:
        """Returns (approver_names_map, dept_name_map).

        approver_names_map: {instance_id -> comma-separated approver names}
        dept_name_map: {dept_id -> dept name}
        """
        from bisheng.database.models.department import DepartmentDao
        from bisheng.user.domain.models.user import UserDao

        pending_tasks = await ApprovalQueryRepository.list_pending_tasks_for_instances(instance_ids)
        inst_approver_map: dict[int, list[int]] = {}
        for task in pending_tasks:
            inst_approver_map.setdefault(task.instance_id, []).append(task.approver_user_id)

        all_approver_ids = list({uid for ids in inst_approver_map.values() for uid in ids})
        user_name_map: dict[int, str] = {}
        if all_approver_ids:
            users = await UserDao.aget_user_by_ids(all_approver_ids)
            user_name_map = {u.user_id: u.user_name for u in (users or [])}

        approver_names_map: dict[int, str] = {}
        for inst_id, uids in inst_approver_map.items():
            names = [user_name_map[uid] for uid in uids if uid in user_name_map]
            if names:
                approver_names_map[inst_id] = '、'.join(names)

        dept_name_map: dict[int, str] = {}
        unique_dept_ids = [d for d in set(dept_ids) if d]
        if unique_dept_ids:
            depts = await DepartmentDao.aget_by_ids(unique_dept_ids)
            dept_name_map = {d.id: d.name for d in depts}

        return approver_names_map, dept_name_map

    @classmethod
    async def list_my_requests(cls, *, tenant_id: int, applicant_user_id: int):
        rows = await ApprovalQueryRepository.list_instances_by_applicant(tenant_id, applicant_user_id)
        if not rows:
            return {'data': [], 'total': 0}

        instance_ids = [r.id for r in rows]
        dept_ids = [r.applicant_department_id for r in rows if r.applicant_department_id]
        approver_names_map, dept_name_map = await cls._enrich_with_approver_and_dept(instance_ids, dept_ids)

        # Batch-check which menu_access instances have had their grant revoked
        from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository
        menu_executed_ids = [
            r.id for r in rows
            if r.scenario_code == 'menu_access_request' and r.status == 'executed'
        ]
        revoked_instance_ids = await UserMenuAccessRepository.get_revoked_instance_ids(menu_executed_ids)

        data = [
            {
                'instance_id': row.id,
                'scenario_code': row.scenario_code,
                'scenario_name': row.scenario_name,
                'business_name': row.business_name,
                'status': row.status,
                'grant_revoked': row.id in revoked_instance_ids,
                'applicant_user_name': row.applicant_user_name,
                'applicant_department_id': row.applicant_department_id,
                'applicant_department_name': dept_name_map.get(row.applicant_department_id) if row.applicant_department_id else None,
                'current_node_name': row.current_node_name,
                'current_approver_names': approver_names_map.get(row.id),
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
        # Enrich with department name and current approver names
        dept_name: str | None = None
        if instance.applicant_department_id:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_by_ids([instance.applicant_department_id])
            if depts:
                dept_name = depts[0].name

        all_task_uids = list({t.approver_user_id for t in tasks})
        task_user_name_map: dict[int, str] = {}
        current_approver_names: str | None = None
        if all_task_uids:
            from bisheng.user.domain.models.user import UserDao
            task_users = await UserDao.aget_user_by_ids(all_task_uids)
            task_user_name_map = {u.user_id: u.user_name for u in (task_users or [])}
            pending_names = [task_user_name_map[t.approver_user_id]
                             for t in tasks if t.status == 'pending' and t.approver_user_id in task_user_name_map]
            if pending_names:
                current_approver_names = '、'.join(pending_names)

        # Fetch full flow node definitions so the frontend can show all nodes,
        # not just tasks that have already been created.
        flow_nodes: list = []
        if instance.flow_version_id:
            from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
            node_defs = await ApprovalScenarioRepository.list_node_definitions(
                instance.tenant_id, instance.flow_version_id
            )
            flow_nodes = [
                {
                    'node_code': nd.node_code,
                    'node_name': nd.node_name,
                    'node_order': nd.node_order,
                    'node_mode': nd.node_mode,
                }
                for nd in node_defs
            ]

        return {
            'instance_id': instance.id,
            'scenario_code': instance.scenario_code,
            'scenario_name': instance.scenario_name,
            'business_name': instance.business_name,
            'status': instance.status,
            'reason': instance.reason,
            'payload_snapshot': instance.payload_snapshot,
            'detail_snapshot': instance.detail_snapshot,
            'applicant_user_name': instance.applicant_user_name,
            'applicant_department_id': instance.applicant_department_id,
            'applicant_department_name': dept_name,
            'current_node_name': instance.current_node_name,
            'current_approver_names': current_approver_names,
            'create_time': instance.create_time,
            'update_time': instance.update_time,
            'tasks': [
                {
                    'task_id': task.id,
                    'approver_user_id': task.approver_user_id,
                    'approver_user_name': task_user_name_map.get(task.approver_user_id),
                    'node_name': task.node_name,
                    'node_order': task.node_order,
                    'node_mode': task.node_mode,
                    'status': task.status,
                    'comment': task.comment,
                    'update_time': task.update_time,
                }
                for task in tasks
            ],
            'flow_nodes': flow_nodes,
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
        ip_address: str | None = None,
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
                task.acted_at = datetime.utcnow()
                await ApprovalInstanceRepository.update_task(task)
        instance.status = ApprovalInstanceStatus.WITHDRAWN
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
            action='approval.request.withdraw',
            target_id=str(instance.id),
            reason=reason,
            metadata={
                'instance_id': instance.id,
                'scenario_code': instance.scenario_code,
                'handler': instance.handler_key or instance.scenario_code,
            },
            operator_name=operator_user_name,
            object_name=instance.business_name,
            ip_address=ip_address,
        )
        # Notify approvers who had tasks on this instance
        task_approver_ids = list({t.approver_user_id for t in tasks if t.approver_user_id != operator_user_id})
        if task_approver_ids:
            await cls._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=task_approver_ids,
                action_code='approval_instance_withdrawn',
                business_name=instance.business_name,
                instance_id=instance.id,
            )
        try:
            from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
            handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
            await handler.on_withdrawn(instance.id, instance.payload_snapshot or {}, reason)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'withdraw_instance: on_withdrawn hook failed for instance %s', instance.id
            )
        return await cls.get_instance_detail(
            instance_id=instance.id,
            login_user=_SystemLoginUser(operator_user_id, tenant_id=instance.tenant_id),
        )

    @classmethod
    async def _send_menu_access_approval_messages(
        cls,
        *,
        applicant_user_id: int,
        applicant_user_name: str,
        instance_id: int,
        task_ids: list[int],
        menu_name: str,
        tenant_id: int,
    ) -> None:
        approver_user_ids: list[int] = []
        seen: set[int] = set()
        for task_id in task_ids:
            task = await ApprovalInstanceRepository.get_task(task_id)
            if task and task.approver_user_id not in seen:
                seen.add(task.approver_user_id)
                approver_user_ids.append(task.approver_user_id)
        if not approver_user_ids:
            return
        from bisheng.core.database import get_async_db_session
        from bisheng.message.api.dependencies import get_message_service as _get_message_service
        async with get_async_db_session() as session:
            message_service = await _get_message_service(session)
            await message_service.send_generic_approval(
                applicant_user_id=applicant_user_id,
                applicant_user_name=applicant_user_name,
                action_code='request_menu_access',
                business_type='approval_instance_id',
                business_id=str(instance_id),
                business_name=menu_name,
                button_action_code='request_menu_access',
                receiver_user_ids=approver_user_ids,
            )

    @classmethod
    async def apply_menu_access_request(
        cls,
        *,
        login_user,
        menu_key: str,
        menu_name: str,
        reason: str | None = None,
        ip_address: str | None = None,
    ):
        db_user = await UserDao.aget_user(login_user.user_id)
        is_department_admin = bool(await DepartmentDao.aget_user_admin_departments(login_user.user_id))
        _, web_menu = await LoginUser.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
        menu_approval_mode = await LoginUser.compute_menu_approval_mode(db_user)
        UserMenuAccessService.ensure_application_allowed(
            menu_approval_mode=menu_approval_mode,
            has_menu_access=menu_key in set(web_menu),
        )

        primary_dept = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
        applicant_department_id = primary_dept.department_id if primary_dept else None

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
                applicant_department_id=applicant_department_id,
                reason=reason,
                payload_snapshot={
                    'menu_key': menu_key,
                    'menu_name': menu_name,
                    'tenant_id': login_user.tenant_id,
                    'applicant_user_id': login_user.user_id,
                },
                ip_address=ip_address,
            )
        )

        if result.decision == ApprovalGateDecision.PENDING and result.task_ids:
            await cls._send_menu_access_approval_messages(
                applicant_user_id=login_user.user_id,
                applicant_user_name=login_user.user_name,
                instance_id=result.instance_id,
                task_ids=result.task_ids,
                menu_name=menu_name,
                tenant_id=login_user.tenant_id,
            )

        return result.model_dump()

    @classmethod
    async def revoke_menu_grant(
        cls,
        *,
        instance_id: int,
        operator_user_id: int,
        reason: str | None = None,
        ip_address: str | None = None,
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
            object_name=instance.business_name,
            ip_address=ip_address,
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
        ip_address: str | None = None,
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
                target_type='approval_task',
                target_id=str(task.id),
                reason=comment,
                metadata={
                    'instance_id': instance.id,
                    'task_id': task.id,
                    'scenario_code': instance.scenario_code,
                    'handler': instance.handler_key or instance.scenario_code,
                },
                operator_name=operator_user_name,
                object_name=instance.business_name,
                ip_address=ip_address,
            )
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code='approval_task_rejected',
                business_name=instance.business_name,
                instance_id=instance.id,
            )
            try:
                from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
                handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
                await handler.on_rejected(instance.id, instance.payload_snapshot or {}, comment)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'decide_task: on_rejected hook failed for instance %s', instance.id
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
            target_type='approval_task',
            target_id=str(task.id),
            reason=comment,
            metadata={
                'instance_id': instance.id,
                'task_id': task.id,
                'scenario_code': instance.scenario_code,
                'handler': instance.handler_key or instance.scenario_code,
            },
            operator_name=operator_user_name,
            object_name=instance.business_name,
            ip_address=ip_address,
        )

        if task.node_mode == 'or':
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.SKIPPED
                    sibling.acted_at = datetime.utcnow()
                    await self.instance_repository.update_task(sibling)
            await self._advance_after_node_approved(instance=instance, current_node_order=task.node_order, operator_user_id=operator_user_id)
            return

        # same_node_tasks was fetched before the current task was updated, so the
        # current task's object still carries its old PENDING status. Treat it as
        # APPROVED by checking its id explicitly.
        all_same_node_approved = all(
            t.id == task.id or t.status == ApprovalTaskStatus.APPROVED
            for t in same_node_tasks
        )
        if all_same_node_approved:
            await self._advance_after_node_approved(instance=instance, current_node_order=task.node_order, operator_user_id=operator_user_id)

    async def _advance_after_node_approved(
        self,
        *,
        instance: ApprovalInstance,
        current_node_order: int,
        operator_user_id: int,
    ) -> None:
        """After a node is fully approved, either advance to the next node or finalize the instance."""
        next_node = None
        if instance.flow_version_id:
            from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
            node_defs = await ApprovalScenarioRepository.list_node_definitions(
                instance.tenant_id, instance.flow_version_id
            )
            sorted_nodes = sorted(node_defs, key=lambda n: n.node_order)
            next_node = next(
                (n for n in sorted_nodes if n.node_order > current_node_order),
                None,
            )

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
            self.__class__._dispatch_outbox(outbox.id)
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code='approval_instance_approved',
                business_name=instance.business_name or '',
                instance_id=instance.id,
            )
            return

        # Resolve approvers for the next node via the scenario handler
        from types import SimpleNamespace

        from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
        try:
            handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
        except KeyError:
            import logging
            logging.getLogger(__name__).error(
                'decide_task: unknown handler_key=%s, finalizing instance %s',
                instance.handler_key, instance.id,
            )
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
            self.__class__._dispatch_outbox(outbox.id)
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code='approval_instance_approved',
                business_name=instance.business_name or '',
                instance_id=instance.id,
            )
            return

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
            from bisheng.approval.domain.models.approval_instance import (
                ApprovalException,
                ApprovalExceptionType,
            )
            instance.status = ApprovalInstanceStatus.EXCEPTION
            instance.current_node_name = next_node.node_name
            await self.instance_repository.update_instance(instance)
            await self.instance_repository.create_exception(
                ApprovalException(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    exception_type=ApprovalExceptionType.APPROVER_EMPTY,
                    detail={
                        'scenario_code': instance.scenario_code,
                        'business_key': instance.business_key,
                        'node_code': next_node.node_code,
                        'node_name': next_node.node_name,
                        'node_order': next_node.node_order,
                        'node_mode': next_node.node_mode,
                    },
                )
            )
            return

        for approver_user_id in approvers:
            await self.instance_repository.create_task(
                ApprovalTask(
                    tenant_id=instance.tenant_id,
                    instance_id=instance.id,
                    flow_version_id=instance.flow_version_id,
                    node_code=next_node.node_code,
                    node_name=next_node.node_name,
                    node_order=next_node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type='resolved',
                    node_mode=next_node.node_mode,
                    status=ApprovalTaskStatus.PENDING,
                )
            )

        instance.current_node_name = next_node.node_name
        await self.instance_repository.update_instance(instance)

    @staticmethod
    async def _send_approval_notify(
        *,
        sender: int,
        receiver_user_ids: list[int],
        action_code: str,
        business_name: str,
        instance_id: int,
    ) -> None:
        if not receiver_user_ids:
            return
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
                    receiver_user_ids=receiver_user_ids,
                    content_item_list=content,
                )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'failed to send approval notify: action_code=%s instance_id=%s', action_code, instance_id
            )

    @staticmethod
    def _dispatch_outbox(outbox_id: int) -> None:
        from bisheng.worker.approval.tasks import execute_approval_outbox
        execute_approval_outbox.delay(outbox_id)

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
        object_name: str | None = None,
        target_type: str = 'approval_instance',
        ip_address: str | None = None,
    ) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=tenant_id,
            operator_id=operator_user_id,
            operator_tenant_id=operator_tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            metadata=metadata,
            operator_name=operator_name,
            object_name=object_name,
            ip_address=ip_address,
        )

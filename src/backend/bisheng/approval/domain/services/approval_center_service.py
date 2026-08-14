from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.ports.scenario_policy import ApprovalDecisionContext
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
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


@dataclass
class _DecisionPostCommitEffects:
    """Keep durable execution dispatch ahead of best-effort notifications."""

    durable: list[tuple] = field(default_factory=list)
    best_effort: list[tuple] = field(default_factory=list)

    def append(self, effect: tuple) -> None:
        self.best_effort.append(effect)

    def append_durable(self, effect: tuple) -> None:
        self.durable.append(effect)


class ApprovalCenterService:
    def __init__(self, *, instance_repository, registry: ApprovalRegistry | None = None) -> None:
        self.instance_repository = instance_repository
        self.registry = registry

    @classmethod
    async def list_my_tasks(cls, *, tenant_id: int, approver_user_id: int):
        tasks = await ApprovalQueryRepository.list_tasks_by_approver(tenant_id, approver_user_id)
        if not tasks:
            return {"data": [], "total": 0}

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
            inst.id for inst in instances if inst.scenario_code == "menu_access_request" and inst.status == "executed"
        ]
        revoked_instance_ids = await UserMenuAccessRepository.get_revoked_instance_ids(menu_executed_ids)

        data = []
        for task in tasks:
            inst = instance_map.get(task.instance_id)
            dept_name = (
                dept_name_map.get(inst.applicant_department_id) if inst and inst.applicant_department_id else None
            )
            data.append(
                {
                    "task_id": task.id,
                    "instance_id": task.instance_id,
                    "scenario_code": inst.scenario_code if inst else None,
                    "scenario_name": inst.scenario_name if inst else None,
                    "business_name": inst.business_name if inst else task.node_name,
                    "status": task.status,
                    "instance_status": inst.status if inst else None,
                    "grant_revoked": task.instance_id in revoked_instance_ids,
                    "current_node_name": task.node_name,
                    "applicant_user_name": inst.applicant_user_name if inst else None,
                    "applicant_department_id": inst.applicant_department_id if inst else None,
                    "applicant_department_name": dept_name,
                    "create_time": task.create_time,
                    "update_time": task.update_time,
                }
            )
        return {"data": data, "total": len(data)}

    @classmethod
    async def count_pending_tasks(cls, *, tenant_id: int, approver_user_id: int) -> int:
        result = await cls.list_my_tasks(
            tenant_id=tenant_id,
            approver_user_id=approver_user_id,
        )
        return sum(1 for row in result["data"] if row["status"] == ApprovalTaskStatus.PENDING)

    @classmethod
    async def count_unread_tasks(cls, *, tenant_id: int, approver_user_id: int) -> int:
        # ApprovalTask has no separate read receipt; pending is the authoritative
        # unread badge source and must use the same Approval task query.
        return await cls.count_pending_tasks(
            tenant_id=tenant_id,
            approver_user_id=approver_user_id,
        )

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
        if (
            not login_user.is_admin()
            and task.approver_user_id != login_user.user_id
            and instance.applicant_user_id != login_user.user_id
        ):
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
                    "node_code": nd.node_code,
                    "node_name": nd.node_name,
                    "node_order": nd.node_order,
                    "node_mode": nd.node_mode,
                }
                for nd in node_defs
            ]

        grant_revoked = False
        if instance.scenario_code == "menu_access_request" and instance.status == "executed":
            from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository

            revoked_ids = await UserMenuAccessRepository.get_revoked_instance_ids([instance.id])
            grant_revoked = instance.id in revoked_ids

        return {
            "task_id": task.id,
            "instance_id": task.instance_id,
            "scenario_code": instance.scenario_code,
            "scenario_name": instance.scenario_name,
            "business_name": instance.business_name,
            "status": task.status,
            "instance_status": instance.status,
            "grant_revoked": grant_revoked,
            "current_node_name": task.node_name,
            "comment": task.comment,
            "detail_snapshot": instance.detail_snapshot,
            "payload_snapshot": instance.payload_snapshot,
            "applicant_user_name": instance.applicant_user_name,
            "applicant_department_id": instance.applicant_department_id,
            "applicant_department_name": dept_name,
            "reason": instance.reason,
            "create_time": instance.create_time,
            "update_time": task.update_time,
            "flow_nodes": flow_nodes,
            "tasks": [
                {
                    "task_id": t.id,
                    "approver_user_id": t.approver_user_id,
                    "approver_user_name": task_user_name_map.get(t.approver_user_id),
                    "node_name": t.node_name,
                    "node_order": t.node_order,
                    "node_mode": t.node_mode,
                    "status": t.status,
                    "comment": t.comment,
                    "update_time": t.update_time,
                }
                for t in all_tasks
            ],
            "action_logs": [
                {
                    "id": log.id,
                    "action": log.action,
                    "operator_user_id": log.operator_user_id,
                    "operator_user_name": log.operator_user_name,
                    "detail": log.detail,
                    "create_time": log.create_time,
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
        # The approval-center dialog decides tasks of every scenario, including the
        # decision-delivery ones (F045/F046), whose policy check needs the bootstrapped
        # registry. Compose it exactly like the public decision application service.
        from bisheng.bootstrap.approval_scenarios import get_approval_scenario_registry

        service = cls(
            instance_repository=ApprovalInstanceRepository,
            registry=get_approval_scenario_registry(),
        )
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
            "task_id": task.id if task else task_id,
            "instance_id": task.instance_id if task else None,
            "status": task.status if task else None,
            "instance_status": instance.status if instance else None,
            "comment": task.comment if task else comment,
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
                approver_names_map[inst_id] = "、".join(names)

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
            return {"data": [], "total": 0}

        instance_ids = [r.id for r in rows]
        dept_ids = [r.applicant_department_id for r in rows if r.applicant_department_id]
        approver_names_map, dept_name_map = await cls._enrich_with_approver_and_dept(instance_ids, dept_ids)

        # Batch-check which menu_access instances have had their grant revoked
        from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository

        menu_executed_ids = [r.id for r in rows if r.scenario_code == "menu_access_request" and r.status == "executed"]
        revoked_instance_ids = await UserMenuAccessRepository.get_revoked_instance_ids(menu_executed_ids)

        data = [
            {
                "instance_id": row.id,
                "scenario_code": row.scenario_code,
                "scenario_name": row.scenario_name,
                "business_name": row.business_name,
                "status": row.status,
                "grant_revoked": row.id in revoked_instance_ids,
                "applicant_user_name": row.applicant_user_name,
                "applicant_department_id": row.applicant_department_id,
                "applicant_department_name": dept_name_map.get(row.applicant_department_id)
                if row.applicant_department_id
                else None,
                "current_node_name": row.current_node_name,
                "current_approver_names": approver_names_map.get(row.id),
                "create_time": row.create_time,
                "update_time": row.update_time,
            }
            for row in rows
        ]
        return {"data": data, "total": len(data)}

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
            pending_names = [
                task_user_name_map[t.approver_user_id]
                for t in tasks
                if t.status == "pending" and t.approver_user_id in task_user_name_map
            ]
            if pending_names:
                current_approver_names = "、".join(pending_names)

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
                    "node_code": nd.node_code,
                    "node_name": nd.node_name,
                    "node_order": nd.node_order,
                    "node_mode": nd.node_mode,
                }
                for nd in node_defs
            ]

        return {
            "instance_id": instance.id,
            "scenario_code": instance.scenario_code,
            "scenario_name": instance.scenario_name,
            "business_name": instance.business_name,
            "status": instance.status,
            "reason": instance.reason,
            "payload_snapshot": instance.payload_snapshot,
            "detail_snapshot": instance.detail_snapshot,
            "applicant_user_name": instance.applicant_user_name,
            "applicant_department_id": instance.applicant_department_id,
            "applicant_department_name": dept_name,
            "current_node_name": instance.current_node_name,
            "current_approver_names": current_approver_names,
            "create_time": instance.create_time,
            "update_time": instance.update_time,
            "tasks": [
                {
                    "task_id": task.id,
                    "approver_user_id": task.approver_user_id,
                    "approver_user_name": task_user_name_map.get(task.approver_user_id),
                    "node_name": task.node_name,
                    "node_order": task.node_order,
                    "node_mode": task.node_mode,
                    "status": task.status,
                    "comment": task.comment,
                    "update_time": task.update_time,
                }
                for task in tasks
            ],
            "flow_nodes": flow_nodes,
            "action_logs": [
                {
                    "id": log.id,
                    "action": log.action,
                    "operator_user_id": log.operator_user_id,
                    "operator_user_name": log.operator_user_name,
                    "detail": log.detail,
                    "create_time": log.create_time,
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
        lookup = await ApprovalInstanceRepository.get_instance(instance_id)
        if lookup is None:
            raise ValueError(f"instance not found: {instance_id}")
        if lookup.applicant_user_id != operator_user_id:
            raise PermissionError("only applicant can withdraw")
        receiver_ids: list[int] = []
        async with ApprovalInstanceRepository.decision_session() as session:
            async with session.begin():
                saved = await ApprovalInstanceRepository.lock_instance_in_session(
                    session,
                    instance_id,
                    tenant_id=int(lookup.tenant_id),
                )
                if saved is None:
                    raise ValueError(f"instance not found: {instance_id}")
                tasks = await ApprovalInstanceRepository.lock_tasks_in_session(
                    session,
                    saved.id,
                    tenant_id=int(saved.tenant_id),
                )
                await ApprovalInstanceRepository.lock_open_exceptions_and_outboxes_in_session(
                    session,
                    saved.id,
                    tenant_id=int(saved.tenant_id),
                )
                if saved.status != ApprovalInstanceStatus.PENDING or saved.applicant_user_id != operator_user_id:
                    raise ApprovalRequestAlreadyProcessedError()
                now = datetime.utcnow()
                for task in tasks:
                    if task.status == ApprovalTaskStatus.PENDING:
                        task.status = ApprovalTaskStatus.CANCELLED
                        task.comment = reason
                        task.acted_at = now
                        session.add(task)
                saved.status = ApprovalInstanceStatus.WITHDRAWN
                session.add(saved)
                session.add(
                    ApprovalActionLog(
                        tenant_id=saved.tenant_id,
                        instance_id=saved.id,
                        action="withdrawn",
                        operator_user_id=operator_user_id,
                        operator_user_name=operator_user_name,
                        detail={"reason": reason},
                    )
                )
                await ApprovalInstanceRepository.create_terminal_decision_event_in_session(
                    session,
                    instance=saved,
                    decision="withdrawn",
                    operator_user_id=operator_user_id,
                )
                await ApprovalInstanceRepository.flush_decision_in_session(session)
                receiver_ids = list(
                    {task.approver_user_id for task in tasks if task.approver_user_id != operator_user_id}
                )
                saved_id = int(saved.id)
                saved_tenant_id = int(saved.tenant_id)
                saved_scenario_code = saved.scenario_code
                saved_handler_key = saved.handler_key
                saved_business_name = saved.business_name
                saved_payload_snapshot = dict(saved.payload_snapshot or {})
        await cls._write_audit_log(
            tenant_id=saved_tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=saved_tenant_id,
            action="approval.request.withdraw",
            target_id=str(saved_id),
            reason=reason,
            metadata={
                "instance_id": saved_id,
                "scenario_code": saved_scenario_code,
                "handler": saved_handler_key or saved_scenario_code,
            },
            operator_name=operator_user_name,
            object_name=saved_business_name,
            ip_address=ip_address,
        )
        if receiver_ids:
            notify = (
                cls._send_invite_notify_best_effort
                if saved_scenario_code == "resource_user_invite_confirmation"
                else cls._send_approval_notify
            )
            notify_reason = reason
            if saved_scenario_code == "resource_user_invite_confirmation" and not notify_reason:
                notify_reason = "邀请已撤回"
            await notify(
                sender=operator_user_id,
                receiver_user_ids=receiver_ids,
                action_code=(
                    "resource_user_invite_failed"
                    if saved_scenario_code == "resource_user_invite_confirmation"
                    else "approval_instance_withdrawn"
                ),
                business_name=saved_business_name,
                instance_id=saved_id,
                scenario_code=saved_scenario_code,
                reason=notify_reason,
            )
        if saved_scenario_code != "resource_user_invite_confirmation":
            await cls._run_terminal_hook_best_effort(
                "on_withdrawn",
                saved_handler_key or saved_scenario_code,
                saved_id,
                payload=saved_payload_snapshot,
                reason=reason,
            )
        return await cls.get_instance_detail(
            instance_id=saved_id,
            login_user=_SystemLoginUser(operator_user_id, tenant_id=saved_tenant_id),
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
                action_code="request_menu_access",
                business_type="approval_instance_id",
                business_id=str(instance_id),
                business_name=menu_name,
                button_action_code="request_menu_access",
                receiver_user_ids=approver_user_ids,
                scenario_code="menu_access_request",
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
        # Resolve the approval flag for the scope this menu belongs to so an
        # admin-area menu can't be applied for when only the workbench scope is on.
        menu_approval_mode = await LoginUser.compute_menu_approval_mode_for_menu(db_user, menu_key)
        UserMenuAccessService.ensure_application_allowed(
            menu_approval_mode=menu_approval_mode,
            has_menu_access=menu_key in set(web_menu),
        )

        primary_dept = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
        applicant_department_id = primary_dept.department_id if primary_dept else None

        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler("menu_access_request", MenuAccessApprovalHandler())
        gate = ApprovalGate(registry=registry)
        result = await gate.request_or_pass(
            ApprovalGateRequest(
                tenant_id=login_user.tenant_id,
                scenario_code="menu_access_request",
                business_key=f"menu:{menu_key}:user:{login_user.user_id}",
                business_resource_type="web_menu",
                business_resource_id=menu_key,
                business_name=menu_name,
                applicant_user_id=login_user.user_id,
                applicant_user_name=login_user.user_name,
                applicant_department_id=applicant_department_id,
                reason=reason,
                payload_snapshot={
                    "menu_key": menu_key,
                    "menu_name": menu_name,
                    "tenant_id": login_user.tenant_id,
                    "applicant_user_id": login_user.user_id,
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
        operator_user_name: str | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
    ):
        instance = await ApprovalInstanceRepository.get_instance(instance_id)
        if instance is None:
            raise ApprovalGrantNotRevokableError()
        menu_key = (instance.payload_snapshot or {}).get("menu_key")
        rows = await UserMenuAccessService.revoke_menu_access(
            tenant_id=instance.tenant_id,
            user_id=instance.applicant_user_id,
            menu_key=menu_key,
            grant_source="approval_instance",
            revoked_by_user_id=operator_user_id,
            revoked_reason=reason,
        )
        if not rows:
            raise ApprovalGrantNotRevokableError()
        await ApprovalInstanceRepository.create_action_log(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action="revoke_grant",
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={"reason": reason, "menu_key": menu_key},
            )
        )
        await cls._write_audit_log(
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            action="approval.menu_access.revoke_grant",
            target_id=str(instance.id),
            reason=reason,
            metadata={
                "scenario_code": instance.scenario_code,
                "menu_key": menu_key,
                "applicant_user_id": instance.applicant_user_id,
            },
            operator_name=operator_user_name,
            object_name=instance.business_name,
            ip_address=ip_address,
        )
        db_user = await UserDao.aget_user(instance.applicant_user_id)
        if db_user:
            is_department_admin = bool(await DepartmentDao.aget_user_admin_departments(instance.applicant_user_id))
            _, web_menu = await LoginUser.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
            if menu_key not in set(web_menu):
                await cls._send_approval_notify(
                    sender=operator_user_id,
                    receiver_user_ids=[instance.applicant_user_id],
                    action_code="menu_grant_revoked",
                    business_name=instance.business_name,
                    instance_id=instance.id,
                    scenario_code=instance.scenario_code,
                    reason=reason,
                )
        return {"revoked_keys": [row.menu_key for row in rows], "instance_id": instance_id}

    async def decide_instance_for_current_approver(
        self,
        *,
        instance_id: int,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        operator_tenant_id: int,
        comment: str | None = None,
        ip_address: str | None = None,
    ) -> dict:
        """Decide the current user's pending task from an instance-oriented UI."""

        return await self._decide_in_uow(
            instance_id=instance_id,
            task_id=None,
            action=action,
            operator_user_id=operator_user_id,
            operator_user_name=operator_user_name,
            operator_tenant_id=operator_tenant_id,
            operator_is_admin=False,
            comment=comment,
            ip_address=ip_address,
        )

    @staticmethod
    async def _reconcile_pending_approvers_locked(*, session, instance: ApprovalInstance, trigger: str) -> tuple:
        """Run an optional scenario-owned assignee reconciliation hook.

        F025 scenarios without dynamic assignees intentionally have no hook.
        F046 supplies it in T011/T012; keeping this optional preserves existing
        scenarios while ensuring both decision entry points reread afterwards.
        """

        if ApprovalInstanceRepository.is_decision_delivery_instance(instance):
            return ()
        try:
            handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
        except KeyError:
            return ()
        reconcile = getattr(handler, "reconcile_pending_approvers", None)
        if reconcile is None:
            return ()
        result = await reconcile(session=session, instance=instance, trigger=trigger)
        return tuple(getattr(result, "post_commit_effects", ()))

    @staticmethod
    async def _authorize_decision(*, handler, instance: ApprovalInstance, operator_user_id: int) -> None:
        authorize = getattr(handler, "authorize_decision", None)
        if authorize is None:
            authorize = getattr(handler, "validate_decision", None)
        if authorize is not None and not await authorize(
            instance=instance,
            operator_user_id=operator_user_id,
        ):
            raise ApprovalRequestPermissionDeniedError()

    async def _decide_in_uow(
        self,
        *,
        instance_id: int | None,
        task_id: int | None,
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        operator_tenant_id: int,
        operator_is_admin: bool,
        comment: str | None,
        ip_address: str | None,
    ) -> dict:
        if action not in {"approve", "reject"}:
            raise ValueError(f"unsupported approval action: {action}")

        post_commit_effects = _DecisionPostCommitEffects()
        async with self.instance_repository.decision_session() as session:
            async with session.begin():
                if instance_id is None:
                    instance_id = await self.instance_repository.get_task_instance_id_in_session(
                        session,
                        task_id,
                        tenant_id=operator_tenant_id,
                    )
                if instance_id is None:
                    raise ApprovalRequestNotFoundError()

                instance = await self.instance_repository.lock_instance_in_session(
                    session,
                    instance_id,
                    tenant_id=operator_tenant_id,
                )
                if instance is None:
                    raise ApprovalRequestNotFoundError()
                if int(instance.tenant_id) != int(operator_tenant_id):
                    raise ApprovalRequestPermissionDeniedError()
                tasks = await self.instance_repository.lock_tasks_in_session(
                    session,
                    instance.id,
                    tenant_id=operator_tenant_id,
                )
                await self.instance_repository.lock_open_exceptions_and_outboxes_in_session(
                    session,
                    instance.id,
                    tenant_id=operator_tenant_id,
                )

                reconcile_effects = await self._reconcile_pending_approvers_locked(
                    session=session,
                    instance=instance,
                    trigger="decision",
                )
                tasks = await self.instance_repository.lock_tasks_in_session(
                    session,
                    instance.id,
                    tenant_id=operator_tenant_id,
                )
                if task_id is None:
                    operator_tasks = [
                        row
                        for row in tasks
                        if row.status == ApprovalTaskStatus.PENDING and row.approver_user_id == operator_user_id
                    ]
                    task = operator_tasks[0] if operator_tasks else None
                    if task is None:
                        raise ApprovalRequestPermissionDeniedError()
                else:
                    task = next((row for row in tasks if row.id == task_id), None)
                    if task is None:
                        raise ApprovalRequestNotFoundError()

                if self.instance_repository.is_decision_delivery_instance(instance):
                    if self.registry is None:
                        raise RuntimeError(
                            f"approval decision-delivery registry is required for scenario={instance.scenario_code}"
                        )
                    business_request_type, business_request_id, request_fingerprint = (
                        self.instance_repository.require_decision_delivery_binding(instance)
                    )
                    policy = self.registry.get_policy(instance.scenario_code)
                    await policy.authorize_decision(
                        ApprovalDecisionContext(
                            tenant_id=int(instance.tenant_id),
                            approval_instance_id=int(instance.id),
                            business_request_type=business_request_type,
                            business_request_id=business_request_id,
                            request_fingerprint=request_fingerprint,
                            operator_user_id=operator_user_id,
                            decision="approved" if action == "approve" else "rejected",
                        )
                    )
                else:
                    try:
                        runtime_handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
                    except KeyError:
                        runtime_handler = None
                    if runtime_handler is not None:
                        await self._authorize_decision(
                            handler=runtime_handler,
                            instance=instance,
                            operator_user_id=operator_user_id,
                        )

                result = await self._decide_locked_task(
                    session=session,
                    instance=instance,
                    task=task,
                    tasks=tasks,
                    action=action,
                    operator_user_id=operator_user_id,
                    operator_user_name=operator_user_name,
                    operator_tenant_id=operator_tenant_id,
                    operator_is_admin=operator_is_admin,
                    comment=comment,
                    ip_address=ip_address,
                    post_commit_effects=post_commit_effects,
                )
                self._append_reconcile_effects(
                    post_commit_effects=post_commit_effects,
                    reconcile_effects=reconcile_effects or (),
                    tasks=tasks,
                )
                await self.instance_repository.flush_decision_in_session(session)

        await self._run_decision_post_commit_effects(post_commit_effects)
        return result

    @staticmethod
    def _append_reconcile_effects(
        *,
        post_commit_effects: _DecisionPostCommitEffects,
        reconcile_effects,
        tasks: list[ApprovalTask],
    ) -> None:
        task_status_by_id = {int(task.id): task.status for task in tasks if task.id is not None}
        prefix = "notify_dynamic_approval_task:"
        for effect in reconcile_effects:
            if effect.name.startswith(prefix):
                try:
                    task_id = int(effect.name.removeprefix(prefix))
                except ValueError:
                    task_id = None
                if task_id is not None and task_status_by_id.get(task_id) != ApprovalTaskStatus.PENDING:
                    continue
            post_commit_effects.append((effect.run, (), {}))

    @staticmethod
    async def _run_decision_post_commit_effects(post_commit_effects: _DecisionPostCommitEffects) -> None:
        for callback, args, kwargs in (*post_commit_effects.durable, *post_commit_effects.best_effort):
            try:
                effect_result = callback(*args, **kwargs)
                if hasattr(effect_result, "__await__"):
                    await effect_result
            except Exception:
                logger.exception(
                    "approval decision post-commit effect failed: callback={}",
                    getattr(callback, "__qualname__", repr(callback)),
                )

    async def _decide_locked_task(
        self,
        *,
        session,
        instance: ApprovalInstance,
        task: ApprovalTask,
        tasks: list[ApprovalTask],
        action: str,
        operator_user_id: int,
        operator_user_name: str,
        operator_tenant_id: int,
        operator_is_admin: bool,
        comment: str | None,
        ip_address: str | None,
        post_commit_effects: _DecisionPostCommitEffects,
    ) -> dict:
        if instance.tenant_id != operator_tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        if instance.status != ApprovalInstanceStatus.PENDING or task.status != ApprovalTaskStatus.PENDING:
            raise ApprovalRequestAlreadyProcessedError()

        is_self_confirmation = instance.scenario_code == "resource_user_invite_confirmation"
        if is_self_confirmation:
            target_user_id = int((instance.payload_snapshot or {}).get("target_user_id", 0))
            if task.approver_user_id != operator_user_id or target_user_id != operator_user_id:
                raise ApprovalRequestPermissionDeniedError()
        elif not operator_is_admin and task.approver_user_id != operator_user_id:
            raise ApprovalRequestPermissionDeniedError()

        now = datetime.utcnow()
        same_node_tasks = [row for row in tasks if row.node_code == task.node_code]
        task.comment = comment
        task.acted_at = now
        instance.latest_approver_user_id = operator_user_id

        if action == "reject":
            task.status = ApprovalTaskStatus.REJECTED
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.CANCELLED
                    sibling.acted_at = now
                    session.add(sibling)
            instance.status = ApprovalInstanceStatus.REJECTED
            await self.instance_repository.create_terminal_decision_event_in_session(
                session,
                instance=instance,
                decision="rejected",
                operator_user_id=operator_user_id,
            )
        else:
            task.status = ApprovalTaskStatus.APPROVED
            node_approved = task.node_mode == "or" or all(
                row.id == task.id or row.status == ApprovalTaskStatus.APPROVED for row in same_node_tasks
            )
            if task.node_mode == "or":
                for sibling in same_node_tasks:
                    if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                        sibling.status = ApprovalTaskStatus.SKIPPED
                        sibling.acted_at = now
                        session.add(sibling)
            if node_approved:
                await self._advance_after_node_approved_locked(
                    session=session,
                    instance=instance,
                    current_node_order=task.node_order,
                    operator_user_id=operator_user_id,
                    post_commit_effects=post_commit_effects,
                )

        session.add(task)
        session.add(instance)
        session.add(
            ApprovalActionLog(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                action="approved" if action == "approve" else "rejected",
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={"task_id": task.id, "comment": comment},
            )
        )
        post_commit_effects.append(
            (
                self.__class__._write_audit_log,
                (),
                {
                    "tenant_id": instance.tenant_id,
                    "operator_user_id": operator_user_id,
                    "operator_tenant_id": instance.tenant_id,
                    "action": "approval.task.approve" if action == "approve" else "approval.task.reject",
                    "target_type": "approval_task",
                    "target_id": str(task.id),
                    "reason": comment,
                    "metadata": {
                        "instance_id": instance.id,
                        "task_id": task.id,
                        "scenario_code": instance.scenario_code,
                        "handler": instance.handler_key or instance.scenario_code,
                    },
                    "operator_name": operator_user_name,
                    "object_name": instance.business_name,
                    "ip_address": ip_address,
                },
            )
        )
        if action == "reject":
            if is_self_confirmation:
                post_commit_effects.append(
                    (
                        self.__class__._send_invite_notify_best_effort,
                        (),
                        {
                            "sender": operator_user_id,
                            "receiver_user_ids": [instance.applicant_user_id],
                            "action_code": "resource_user_invite_failed",
                            "business_name": instance.business_name,
                            "instance_id": instance.id,
                            "scenario_code": instance.scenario_code,
                            "reason": comment or "invitation rejected",
                        },
                    )
                )
            else:
                post_commit_effects.append(
                    (
                        self.__class__._send_approval_notify,
                        (),
                        {
                            "sender": operator_user_id,
                            "receiver_user_ids": [instance.applicant_user_id],
                            "action_code": "approval_task_rejected",
                            "business_name": instance.business_name,
                            "instance_id": instance.id,
                            "scenario_code": instance.scenario_code,
                            "reason": comment,
                        },
                    )
                )
                post_commit_effects.append(
                    (
                        self.__class__._run_terminal_hook_best_effort,
                        ("on_rejected", instance.handler_key or instance.scenario_code, instance.id),
                        {"payload": instance.payload_snapshot or {}, "reason": comment},
                    )
                )

        return {
            "task_id": task.id,
            "instance_id": instance.id,
            "status": task.status,
            "instance_status": instance.status,
        }

    async def _advance_after_node_approved_locked(
        self,
        *,
        session,
        instance: ApprovalInstance,
        current_node_order: int,
        operator_user_id: int,
        post_commit_effects: _DecisionPostCommitEffects,
    ) -> ApprovalOutbox | None:
        next_node = None
        if instance.flow_version_id:
            node_defs = await self.instance_repository.list_flow_nodes_in_session(
                session,
                tenant_id=instance.tenant_id,
                flow_version_id=instance.flow_version_id,
            )
            next_node = next((node for node in node_defs if node.node_order > current_node_order), None)

        if next_node is None:
            return await self._finalize_instance_locked(
                session=session,
                instance=instance,
                operator_user_id=operator_user_id,
                post_commit_effects=post_commit_effects,
            )

        from types import SimpleNamespace

        from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler

        try:
            handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
        except KeyError:
            return await self._finalize_instance_locked(
                session=session,
                instance=instance,
                operator_user_id=operator_user_id,
                post_commit_effects=post_commit_effects,
            )

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
            session.add(
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
            post_commit_effects.append(
                (
                    self.__class__._notify_admins_of_approver_empty,
                    (),
                    {
                        "tenant_id": instance.tenant_id,
                        "applicant_user_id": instance.applicant_user_id,
                        "business_name": instance.business_name,
                        "instance_id": instance.id,
                        "scenario_code": instance.scenario_code,
                    },
                )
            )
            return None

        instance.current_node_name = next_node.node_name
        for approver_user_id in approvers:
            next_task = ApprovalTask(
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
            session.add(next_task)
            await session.flush()
            post_commit_effects.append(
                (
                    self.__class__._send_approval_notify,
                    (),
                    {
                        "sender": instance.applicant_user_id,
                        "receiver_user_ids": [next_task.approver_user_id],
                        "action_code": "approval_task_pending",
                        "business_name": instance.business_name,
                        "instance_id": instance.id,
                        "scenario_code": instance.scenario_code,
                        "task_id": next_task.id,
                    },
                )
            )
        return None

    async def _finalize_instance_locked(
        self,
        *,
        session,
        instance: ApprovalInstance,
        operator_user_id: int,
        post_commit_effects: _DecisionPostCommitEffects,
    ) -> ApprovalOutbox | None:
        instance.status = ApprovalInstanceStatus.APPROVED
        instance.current_node_name = None
        if self.instance_repository.is_decision_delivery_instance(instance):
            await self.instance_repository.create_terminal_decision_event_in_session(
                session,
                instance=instance,
                decision="approved",
                operator_user_id=operator_user_id,
            )
            post_commit_effects.append(
                (
                    self.__class__._send_approval_notify,
                    (),
                    {
                        "sender": operator_user_id,
                        "receiver_user_ids": [instance.applicant_user_id],
                        "action_code": "approval_instance_approved",
                        "business_name": instance.business_name or "",
                        "instance_id": instance.id,
                        "scenario_code": instance.scenario_code,
                    },
                )
            )
            return None
        outbox = ApprovalOutbox(
            tenant_id=instance.tenant_id,
            instance_id=instance.id,
            handler_key=instance.handler_key or instance.scenario_code,
            status=ApprovalOutboxStatus.PENDING,
            payload_snapshot=instance.payload_snapshot or {},
        )
        session.add(outbox)
        await session.flush()
        post_commit_effects.append_durable((self.__class__._dispatch_outbox, (outbox.id, int(instance.tenant_id)), {}))
        if instance.scenario_code != "resource_user_invite_confirmation":
            post_commit_effects.append(
                (
                    self.__class__._send_approval_notify,
                    (),
                    {
                        "sender": operator_user_id,
                        "receiver_user_ids": [instance.applicant_user_id],
                        "action_code": "approval_instance_approved",
                        "business_name": instance.business_name or "",
                        "instance_id": instance.id,
                        "scenario_code": instance.scenario_code,
                    },
                )
            )
        return outbox

    @staticmethod
    async def _notify_admins_of_approver_empty(**kwargs) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_admins(
            action_code="approval_exception_approver_empty",
            **kwargs,
        )

    @staticmethod
    async def _run_terminal_hook_best_effort(
        hook_name: str,
        handler_key: str,
        instance_id: int,
        *,
        payload: dict,
        reason: str | None,
    ) -> None:
        try:
            from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler

            handler = await build_runtime_handler(handler_key)
            await getattr(handler, hook_name)(instance_id, payload, reason)
        except Exception:
            logger.exception("approval terminal hook failed: instance_id={} hook={}", instance_id, hook_name)

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
        if self.instance_repository is ApprovalInstanceRepository:
            await self._decide_in_uow(
                instance_id=None,
                task_id=task_id,
                action=action,
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                operator_tenant_id=operator_tenant_id,
                operator_is_admin=operator_is_admin,
                comment=comment,
                ip_address=ip_address,
            )
            return
        task = await self.instance_repository.get_task(task_id)
        if task is None:
            raise ApprovalRequestNotFoundError()
        instance = await self.instance_repository.get_instance(task.instance_id)
        if instance is None:
            raise ApprovalRequestNotFoundError()
        if instance.tenant_id != operator_tenant_id:
            raise ApprovalRequestPermissionDeniedError()
        if instance.scenario_code == "resource_user_invite_confirmation":
            target_user_id = int((instance.payload_snapshot or {}).get("target_user_id", 0))
            if task.approver_user_id != operator_user_id or target_user_id != operator_user_id:
                raise ApprovalRequestPermissionDeniedError()
            decision = await self.instance_repository.decide_single_task(
                task_id=task_id,
                operator_user_id=operator_user_id,
                action=action,
                operator_user_name=operator_user_name,
                comment=comment,
            )
            if decision is None:
                raise ApprovalRequestAlreadyProcessedError()
            await self.__class__._write_audit_log(
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                action="approval.task.approve" if action == "approve" else "approval.task.reject",
                target_type="approval_task",
                target_id=str(task.id),
                reason=comment,
                metadata={
                    "instance_id": instance.id,
                    "task_id": task.id,
                    "scenario_code": instance.scenario_code,
                },
                operator_name=operator_user_name,
                object_name=instance.business_name,
                ip_address=ip_address,
            )
            if decision.outbox is not None:
                self.__class__._dispatch_outbox(decision.outbox.id, int(instance.tenant_id))
            else:
                await self.__class__._send_invite_notify_best_effort(
                    sender=operator_user_id,
                    receiver_user_ids=[instance.applicant_user_id],
                    action_code="resource_user_invite_failed",
                    business_name=instance.business_name,
                    instance_id=instance.id,
                    scenario_code=instance.scenario_code,
                    reason=comment or "被邀请用户已拒绝",
                )
            return
        if not operator_is_admin and task.approver_user_id != operator_user_id:
            raise ApprovalRequestPermissionDeniedError()
        if task.status != ApprovalTaskStatus.PENDING:
            raise ApprovalRequestAlreadyProcessedError()

        sibling_tasks = await self.instance_repository.list_tasks(instance.id)
        same_node_tasks = [one for one in sibling_tasks if one.node_code == task.node_code]

        if action == "reject":
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
                    action="rejected",
                    operator_user_id=operator_user_id,
                    operator_user_name=operator_user_name,
                    detail={"comment": comment},
                )
            )
            await self.__class__._write_audit_log(
                tenant_id=instance.tenant_id,
                operator_user_id=operator_user_id,
                operator_tenant_id=instance.tenant_id,
                action="approval.task.reject",
                target_type="approval_task",
                target_id=str(task.id),
                reason=comment,
                metadata={
                    "instance_id": instance.id,
                    "task_id": task.id,
                    "scenario_code": instance.scenario_code,
                    "handler": instance.handler_key or instance.scenario_code,
                },
                operator_name=operator_user_name,
                object_name=instance.business_name,
                ip_address=ip_address,
            )
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code="approval_task_rejected",
                business_name=instance.business_name,
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
                reason=comment,
            )
            try:
                from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler

                handler = await build_runtime_handler(instance.handler_key or instance.scenario_code)
                await handler.on_rejected(instance.id, instance.payload_snapshot or {}, comment)
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "decide_task: on_rejected hook failed for instance %s", instance.id
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
                action="approved",
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                detail={"task_id": task.id, "comment": comment},
            )
        )
        await self.__class__._write_audit_log(
            tenant_id=instance.tenant_id,
            operator_user_id=operator_user_id,
            operator_tenant_id=instance.tenant_id,
            action="approval.task.approve",
            target_type="approval_task",
            target_id=str(task.id),
            reason=comment,
            metadata={
                "instance_id": instance.id,
                "task_id": task.id,
                "scenario_code": instance.scenario_code,
                "handler": instance.handler_key or instance.scenario_code,
            },
            operator_name=operator_user_name,
            object_name=instance.business_name,
            ip_address=ip_address,
        )

        if task.node_mode == "or":
            for sibling in same_node_tasks:
                if sibling.id != task.id and sibling.status == ApprovalTaskStatus.PENDING:
                    sibling.status = ApprovalTaskStatus.SKIPPED
                    sibling.acted_at = datetime.utcnow()
                    await self.instance_repository.update_task(sibling)
            await self._advance_after_node_approved(
                instance=instance, current_node_order=task.node_order, operator_user_id=operator_user_id
            )
            return

        # same_node_tasks was fetched before the current task was updated, so the
        # current task's object still carries its old PENDING status. Treat it as
        # APPROVED by checking its id explicitly.
        all_same_node_approved = all(
            t.id == task.id or t.status == ApprovalTaskStatus.APPROVED for t in same_node_tasks
        )
        if all_same_node_approved:
            await self._advance_after_node_approved(
                instance=instance, current_node_order=task.node_order, operator_user_id=operator_user_id
            )

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
            self.__class__._dispatch_outbox(outbox.id, int(instance.tenant_id))
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code="approval_instance_approved",
                business_name=instance.business_name or "",
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
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
                "decide_task: unknown handler_key=%s, finalizing instance %s",
                instance.handler_key,
                instance.id,
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
            self.__class__._dispatch_outbox(outbox.id, int(instance.tenant_id))
            await self.__class__._send_approval_notify(
                sender=operator_user_id,
                receiver_user_ids=[instance.applicant_user_id],
                action_code="approval_instance_approved",
                business_name=instance.business_name or "",
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
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
                        "scenario_code": instance.scenario_code,
                        "business_key": instance.business_key,
                        "node_code": next_node.node_code,
                        "node_name": next_node.node_name,
                        "node_order": next_node.node_order,
                        "node_mode": next_node.node_mode,
                    },
                )
            )
            from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

            await ApprovalNotificationService.notify_admins(
                tenant_id=instance.tenant_id,
                applicant_user_id=instance.applicant_user_id,
                action_code="approval_exception_approver_empty",
                business_name=instance.business_name,
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
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

        instance.current_node_name = next_node.node_name
        await self.instance_repository.update_instance(instance)
        for task in created_tasks:
            await self.__class__._send_approval_notify(
                sender=instance.applicant_user_id,
                receiver_user_ids=[task.approver_user_id],
                action_code="approval_task_pending",
                business_name=instance.business_name,
                instance_id=instance.id,
                scenario_code=instance.scenario_code,
                task_id=task.id,
            )

    @staticmethod
    async def _send_approval_notify(
        *,
        sender: int,
        receiver_user_ids: list[int],
        action_code: str,
        business_name: str,
        instance_id: int,
        scenario_code: str | None = None,
        reason: str | None = None,
        task_id: int | None = None,
    ) -> None:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_users(
            sender=sender,
            receiver_user_ids=receiver_user_ids,
            action_code=action_code,
            business_name=business_name,
            instance_id=instance_id,
            scenario_code=scenario_code,
            reason=reason,
            task_id=task_id,
        )

    @classmethod
    async def _send_invite_notify_best_effort(cls, **kwargs) -> None:
        try:
            await cls._send_approval_notify(**kwargs)
        except Exception:
            # Instance/task terminal state is authoritative; reminders are best effort.
            logger.exception(
                "failed to send resource invite decision reminder: instance_id={} action_code={}",
                kwargs.get("instance_id"),
                kwargs.get("action_code"),
            )

    @staticmethod
    def _dispatch_outbox(outbox_id: int, tenant_id: int) -> None:
        from bisheng.worker.approval.tasks import execute_approval_outbox

        tenant_id = int(tenant_id)
        if tenant_id <= 0:
            raise ValueError("a positive tenant_id is required to dispatch an approval outbox")
        execute_approval_outbox.apply_async(args=[outbox_id], headers={"tenant_id": tenant_id})

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
        target_type: str = "approval_instance",
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

from __future__ import annotations

from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
)
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.department_file_view_handler import (
    DepartmentFileViewApprovalHandler,
)
from bisheng.common.errcode.approval import (
    ApprovalApproverUnavailableError,
    ApprovalDepartmentFileGrantNotRevokableError,
    ApprovalDepartmentFileInvalidBindingError,
    ApprovalFixedScenarioInvalidError,
    ApprovalReasonRequiredError,
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
    ApprovalScenarioDisabledError,
)
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import UserDepartment
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)


class DepartmentFileViewApprovalService:
    SCENARIO_CODE = "department_file_view_request"
    MAX_REASON_LENGTH = 2000

    def __init__(
        self,
        *,
        session,
        file_repository,
        access_service,
        provisioner=None,
    ) -> None:
        self.session = session
        self.file_repository = file_repository
        self.access_service = access_service
        self.provisioner = provisioner

    @classmethod
    def normalize_reason(cls, reason: str | None) -> str:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ApprovalReasonRequiredError()
        if len(normalized) > cls.MAX_REASON_LENGTH:
            raise ValueError("申请原因不能超过 2000 个字符")
        return normalized

    async def apply(
        self,
        *,
        login_user,
        space_id: int,
        file_id: int,
        reason: str | None,
        ip_address: str | None = None,
    ):
        reason = self.normalize_reason(reason)
        tenant_id = int(login_user.tenant_id)
        try:
            file = await self.file_repository.find_by_id_for_update(file_id)
            if file is None or int(getattr(file, "knowledge_id", 0) or 0) != int(space_id):
                raise ApprovalDepartmentFileInvalidBindingError()

            decision = await self.access_service.evaluate_file(
                login_user=login_user,
                file=file,
            )
            if decision.allowed:
                await self.session.rollback()
                return self._access_payload(
                    space_id=space_id,
                    file_id=file_id,
                    decision=decision,
                    status="allowed",
                )
            if decision.status != DepartmentFileAccessStatus.APPROVAL_REQUIRED:
                raise ApprovalDepartmentFileInvalidBindingError()

            resource = await self.access_service.load_resource(file)
            if not resource.valid or resource.department_id is None or int(resource.file.knowledge_id) != int(space_id):
                raise ApprovalDepartmentFileInvalidBindingError()

            approver_user_ids = sorted(
                await self.access_service.resolve_department_approvers(int(resource.department_id))
            )
            if not approver_user_ids:
                raise ApprovalApproverUnavailableError()
            if int(login_user.user_id) in approver_user_ids:
                await self.session.rollback()
                return self._access_payload(
                    space_id=space_id,
                    file_id=file_id,
                    decision=decision,
                    status="allowed",
                    access_source="department_approver",
                )

            applicant_department_id = await self._get_applicant_department_id(
                int(login_user.user_id)
            )
            route_context = {
                "file_department_id": int(resource.department_id),
                "file_knowledge_space_id": int(resource.file.knowledge_id),
            }
            if self.provisioner is None:
                return await self._apply_with_gate(
                    login_user=login_user,
                    tenant_id=tenant_id,
                    space_id=int(space_id),
                    file_id=int(file_id),
                    file=file,
                    resource=resource,
                    decision=decision,
                    applicant_department_id=applicant_department_id,
                    route_context=route_context,
                    reason=reason,
                    ip_address=ip_address,
                )
            contract = await self._get_application_contract(
                tenant_id=tenant_id,
                login_user=login_user,
                applicant_department_id=applicant_department_id,
                space_id=int(space_id),
                file_id=int(file_id),
                file_name=str(getattr(file, "file_name", "") or ""),
                route_context=route_context,
            )

            duplicate = await self._find_latest_instance(
                tenant_id=tenant_id,
                applicant_user_id=int(login_user.user_id),
                space_id=int(space_id),
                file_id=int(file_id),
                statuses=(
                    ApprovalInstanceStatus.PENDING,
                    ApprovalInstanceStatus.APPROVED,
                    ApprovalInstanceStatus.EXECUTING,
                    ApprovalInstanceStatus.EXCEPTION,
                    ApprovalInstanceStatus.EXECUTE_FAILED,
                ),
                for_update=True,
            )
            if duplicate is not None:
                tasks = await self._list_tasks(duplicate.id)
                await self.session.rollback()
                return {
                    "status": "pending",
                    "content_access": decision.status,
                    "space_id": int(space_id),
                    "file_id": int(file_id),
                    "instance_id": int(duplicate.id),
                    "latest_instance_status": duplicate.status,
                    "task_ids": [int(task.id) for task in tasks],
                    "can_download": bool(decision.can_download),
                }

            safe_metadata = await self._project_safe_metadata(
                file_record=file,
                space_name=str(getattr(resource.space, "name", "") or ""),
                decision=decision,
            )
            instance = ApprovalInstance(
                tenant_id=tenant_id,
                scenario_code=self.SCENARIO_CODE,
                scenario_name=contract.scenario.scenario_name,
                handler_key=self.SCENARIO_CODE,
                business_key=f"department-file:{space_id}:{file_id}",
                business_resource_type="department_knowledge_file",
                business_resource_id=str(file_id),
                business_name=str(getattr(file, "file_name", "") or ""),
                applicant_user_id=int(login_user.user_id),
                applicant_user_name=str(login_user.user_name or ""),
                applicant_department_id=applicant_department_id,
                flow_version_id=int(contract.flow_version.id),
                route_rule_id=int(contract.route.id),
                status=ApprovalInstanceStatus.PENDING,
                reason=reason,
                payload_snapshot={
                    "tenant_id": tenant_id,
                    "applicant_user_id": int(login_user.user_id),
                    "space_id": int(space_id),
                    "file_id": int(file_id),
                    "file_name": str(getattr(file, "file_name", "") or ""),
                    "space_name": str(getattr(resource.space, "name", "") or ""),
                    "department_id": int(resource.department_id),
                    "department_name": str(getattr(resource.department, "name", "") or ""),
                    **route_context,
                },
                detail_snapshot={
                    **safe_metadata,
                    "department_id": int(resource.department_id),
                    "department_name": str(getattr(resource.department, "name", "") or ""),
                    "reason": reason,
                },
                current_node_name=contract.node.node_name,
            )
            self.session.add(instance)
            await self.session.flush()
            tasks = [
                ApprovalTask(
                    tenant_id=tenant_id,
                    instance_id=int(instance.id),
                    flow_version_id=int(contract.flow_version.id),
                    node_code=contract.node.node_code,
                    node_name=contract.node.node_name,
                    node_order=contract.node.node_order,
                    approver_user_id=approver_user_id,
                    approver_source_type="department_file_approvers",
                    node_mode="or",
                    status=ApprovalTaskStatus.PENDING,
                )
                for approver_user_id in approver_user_ids
            ]
            self.session.add_all(tasks)
            self.session.add(
                ApprovalActionLog(
                    tenant_id=tenant_id,
                    instance_id=int(instance.id),
                    action="submitted",
                    operator_user_id=int(login_user.user_id),
                    operator_user_name=str(login_user.user_name or ""),
                    detail={
                        "space_id": int(space_id),
                        "file_id": int(file_id),
                    },
                )
            )
            self.session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    operator_id=int(login_user.user_id),
                    operator_name=str(login_user.user_name or ""),
                    operator_tenant_id=tenant_id,
                    action="approval.request.submit",
                    target_type="approval_instance",
                    target_id=str(instance.id),
                    reason=reason,
                    audit_metadata={
                        "instance_id": int(instance.id),
                        "scenario_code": self.SCENARIO_CODE,
                        "handler": self.SCENARIO_CODE,
                        "business_resource_type": "department_knowledge_file",
                        "business_resource_id": str(file_id),
                        "space_id": int(space_id),
                        "file_id": int(file_id),
                        "department_id": int(resource.department_id),
                    },
                    object_name=instance.business_name,
                    ip_address=ip_address,
                )
            )
            await self.session.flush()
            task_ids = [int(task.id) for task in tasks]
            instance_id = int(instance.id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        await self._notify_approvers(
            applicant_user_id=int(login_user.user_id),
            applicant_user_name=str(login_user.user_name or ""),
            approver_user_ids=approver_user_ids,
            business_name=instance.business_name,
            instance_id=instance_id,
            task_ids=task_ids,
        )
        return {
            "status": "pending",
            "content_access": decision.status,
            "space_id": int(space_id),
            "file_id": int(file_id),
            "instance_id": instance_id,
            "latest_instance_status": ApprovalInstanceStatus.PENDING,
            "task_ids": task_ids,
            "can_download": bool(decision.can_download),
        }

    async def status(
        self,
        *,
        login_user,
        space_id: int,
        file_id: int,
    ) -> dict:
        file = await self.file_repository.find_by_id(file_id)
        if file is None or int(getattr(file, "knowledge_id", 0) or 0) != int(space_id):
            return self._invalid_status(space_id=space_id, file_id=file_id)

        decision = await self.access_service.evaluate_file(
            login_user=login_user,
            file=file,
        )
        resource = await self.access_service.load_resource(file)
        if decision.status == DepartmentFileAccessStatus.NOT_APPLICABLE:
            # 公共库等非部门空间不进入本审批场景。门户详情仍会继续执行原有
            # 内容端点鉴权。这里只表示“不需要部门文件审批”。
            safe_metadata = await self._project_safe_metadata(
                file_record=file,
                space_name=str(getattr(resource.space, "name", "") or ""),
                decision=decision,
            )
            return {
                "space_id": int(space_id),
                "file_id": int(file_id),
                "status": "allowed",
                "content_access": "allowed",
                "access_source": None,
                "can_download": bool(decision.can_download),
                "instance_id": None,
                "latest_instance_status": None,
                "safe_metadata": safe_metadata,
            }
        if (
            decision.status == DepartmentFileAccessStatus.UNAVAILABLE
            or not resource.valid
            or resource.department_id is None
        ):
            return self._invalid_status(
                space_id=space_id,
                file_id=file_id,
                can_download=decision.can_download,
            )

        safe_metadata = await self._project_safe_metadata(
            file_record=file,
            space_name=str(getattr(resource.space, "name", "") or ""),
            decision=decision,
        )
        if decision.allowed:
            return self._access_payload(
                space_id=space_id,
                file_id=file_id,
                decision=decision,
                status="allowed",
                safe_metadata=safe_metadata,
            )

        latest = await self._find_latest_instance(
            tenant_id=int(login_user.tenant_id),
            applicant_user_id=int(login_user.user_id),
            space_id=int(space_id),
            file_id=int(file_id),
        )
        if latest is not None and latest.status in {
            ApprovalInstanceStatus.PENDING,
            ApprovalInstanceStatus.APPROVED,
            ApprovalInstanceStatus.EXECUTING,
            ApprovalInstanceStatus.EXCEPTION,
            ApprovalInstanceStatus.EXECUTE_FAILED,
        }:
            return self._access_payload(
                space_id=space_id,
                file_id=file_id,
                decision=decision,
                status="pending",
                safe_metadata=safe_metadata,
                instance=latest,
            )

        if not await self._is_scenario_enabled(
            tenant_id=int(login_user.tenant_id)
        ):
            return self._access_payload(
                space_id=space_id,
                file_id=file_id,
                decision=decision,
                status="scenario_disabled",
                safe_metadata=safe_metadata,
                instance=latest,
            )
        approvers = await self.access_service.resolve_department_approvers(int(resource.department_id))
        if not approvers:
            return self._access_payload(
                space_id=space_id,
                file_id=file_id,
                decision=decision,
                status="approver_unavailable",
                safe_metadata=safe_metadata,
                instance=latest,
            )
        terminal_status = (
            latest.status
            if latest is not None
            and latest.status
            in {
                ApprovalInstanceStatus.REJECTED,
                ApprovalInstanceStatus.WITHDRAWN,
            }
            else "approval_required"
        )
        return self._access_payload(
            space_id=space_id,
            file_id=file_id,
            decision=decision,
            status=terminal_status,
            safe_metadata=safe_metadata,
            instance=latest,
        )

    async def _project_safe_metadata(
        self,
        *,
        file_record,
        space_name: str,
        decision,
    ) -> dict:
        return DepartmentFileViewAccessService.project_safe_metadata(
            file_record=file_record,
            space_name=space_name,
            decision=decision,
            folder_path=await self._resolve_folder_display_path(file_record),
        )

    async def _resolve_folder_display_path(self, file_record) -> str:
        folder_ids = [
            int(part)
            for part in str(
                getattr(file_record, "file_level_path", "") or ""
            ).split("/")
            if part.isdigit()
        ]
        if not folder_ids:
            return "根目录"

        find_by_ids = getattr(self.file_repository, "find_by_ids", None)
        if not callable(find_by_ids):
            return "/".join("目录已删除" for _ in folder_ids)

        folders = await find_by_ids(folder_ids)
        if not isinstance(folders, (list, tuple)):
            return "/".join("目录已删除" for _ in folder_ids)

        knowledge_id = int(getattr(file_record, "knowledge_id", 0) or 0)
        folder_names = {
            int(folder.id): str(getattr(folder, "file_name", "") or "").strip()
            for folder in folders
            if getattr(folder, "id", None) is not None
            and int(getattr(folder, "knowledge_id", 0) or 0) == knowledge_id
        }
        return "/".join(
            folder_names.get(folder_id) or "目录已删除"
            for folder_id in folder_ids
        )

    async def _apply_with_gate(
        self,
        *,
        login_user,
        tenant_id: int,
        space_id: int,
        file_id: int,
        file,
        resource,
        decision,
        applicant_department_id: int | None,
        route_context: dict,
        reason: str,
        ip_address: str | None,
    ) -> dict:
        payload_snapshot = {
            "tenant_id": tenant_id,
            "applicant_user_id": int(login_user.user_id),
            "space_id": space_id,
            "file_id": file_id,
            "file_name": str(getattr(file, "file_name", "") or ""),
            "space_name": str(getattr(resource.space, "name", "") or ""),
            "department_id": int(resource.department_id),
            "department_name": str(
                getattr(resource.department, "name", "") or ""
            ),
            **route_context,
        }
        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler(
            self.SCENARIO_CODE,
            DepartmentFileViewApprovalHandler(),
        )
        result = await ApprovalGate(
            registry=registry,
            session=self.session,
        ).request_or_pass(
            ApprovalGateRequest(
                tenant_id=tenant_id,
                scenario_code=self.SCENARIO_CODE,
                business_key=f"department-file:{space_id}:{file_id}",
                business_resource_type="department_knowledge_file",
                business_resource_id=str(file_id),
                business_name=str(
                    getattr(file, "file_name", "") or ""
                ),
                applicant_user_id=int(login_user.user_id),
                applicant_user_name=str(login_user.user_name or ""),
                applicant_department_id=applicant_department_id,
                reason=reason,
                payload_snapshot=payload_snapshot,
                ip_address=ip_address,
            )
        )
        status = {
            ApprovalGateDecision.PASS: "pending",
            ApprovalGateDecision.PENDING: "pending",
            ApprovalGateDecision.EXCEPTION: "exception",
        }[result.decision]
        return {
            "status": status,
            "content_access": decision.status,
            "space_id": space_id,
            "file_id": file_id,
            "instance_id": int(result.instance_id),
            "latest_instance_status": (
                ApprovalInstanceStatus.APPROVED
                if result.decision == ApprovalGateDecision.PASS
                else (
                    ApprovalInstanceStatus.EXCEPTION
                    if result.decision == ApprovalGateDecision.EXCEPTION
                    else ApprovalInstanceStatus.PENDING
                )
            ),
            "task_ids": [int(task_id) for task_id in result.task_ids],
            "can_download": bool(decision.can_download),
        }

    async def _is_scenario_enabled(self, *, tenant_id: int) -> bool:
        if self.provisioner is not None:
            contract = await self.provisioner.get_contract(
                tenant_id=tenant_id,
                require_enabled=False,
            )
            return bool(contract.scenario.enabled)
        scenario = (
            (
                await self.session.execute(
                    select(ApprovalScenario).where(
                        ApprovalScenario.tenant_id == tenant_id,
                        ApprovalScenario.scenario_code == self.SCENARIO_CODE,
                    )
                )
            )
            .scalars()
            .first()
        )
        return bool(scenario and scenario.enabled)

    async def _get_application_contract(
        self,
        *,
        tenant_id: int,
        login_user,
        applicant_department_id: int | None,
        space_id: int,
        file_id: int,
        file_name: str,
        route_context: dict,
    ):
        if self.provisioner is not None:
            return await self.provisioner.get_contract(
                tenant_id=tenant_id,
                require_enabled=True,
            )

        scenario = (
            (
                await self.session.execute(
                    select(ApprovalScenario).where(
                        ApprovalScenario.tenant_id == tenant_id,
                        ApprovalScenario.scenario_code == self.SCENARIO_CODE,
                    )
                )
            )
            .scalars()
            .first()
        )
        if scenario is None or not scenario.enabled:
            raise ApprovalScenarioDisabledError()

        routes = list(
            (
                await self.session.execute(
                    select(ApprovalRouteRule)
                    .where(
                        ApprovalRouteRule.tenant_id == tenant_id,
                        ApprovalRouteRule.scenario_id == scenario.id,
                        (ApprovalRouteRule.enabled == True),  # noqa: E712
                    )
                    .order_by(
                        ApprovalRouteRule.sort_order.asc(),
                        ApprovalRouteRule.id.asc(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        request = ApprovalGateRequest(
            tenant_id=tenant_id,
            scenario_code=self.SCENARIO_CODE,
            business_key=f"department-file:{space_id}:{file_id}",
            business_resource_type="department_knowledge_file",
            business_resource_id=str(file_id),
            business_name=file_name,
            applicant_user_id=int(login_user.user_id),
            applicant_user_name=str(login_user.user_name or ""),
            applicant_department_id=applicant_department_id,
            payload_snapshot=dict(route_context),
        )
        route = await ApprovalGate(registry=None)._match_first_route(
            routes,
            request,
        )
        if route is None or route.route_type == "pass":
            # pass 与通用 outbox/grant 编排在后续 runtime task 中接入;
            # 这里禁止退回固定流程, 避免忽略管理员配置。
            raise ApprovalFixedScenarioInvalidError()

        flow = (
            (
                await self.session.execute(
                    select(ApprovalFlowDefinition)
                    .where(
                        ApprovalFlowDefinition.id
                        == route.flow_definition_id,
                        ApprovalFlowDefinition.tenant_id == tenant_id,
                        ApprovalFlowDefinition.scenario_id == scenario.id,
                        (ApprovalFlowDefinition.is_active == True),  # noqa: E712
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if flow is None:
            raise ApprovalFixedScenarioInvalidError()
        flow_version = (
            (
                await self.session.execute(
                    select(ApprovalFlowVersion)
                    .where(
                        ApprovalFlowVersion.tenant_id == tenant_id,
                        ApprovalFlowVersion.flow_definition_id == flow.id,
                        (ApprovalFlowVersion.is_active == True),  # noqa: E712
                    )
                    .order_by(
                        ApprovalFlowVersion.version_no.desc(),
                        ApprovalFlowVersion.id.desc(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .first()
        )
        if flow_version is None:
            raise ApprovalFixedScenarioInvalidError()
        nodes = list(
            (
                await self.session.execute(
                    select(ApprovalNodeDefinition)
                    .where(
                        ApprovalNodeDefinition.tenant_id == tenant_id,
                        ApprovalNodeDefinition.flow_version_id
                        == flow_version.id,
                    )
                    .order_by(
                        ApprovalNodeDefinition.node_order.asc(),
                        ApprovalNodeDefinition.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not nodes:
            raise ApprovalFixedScenarioInvalidError()

        from types import SimpleNamespace

        return SimpleNamespace(
            scenario=scenario,
            route=route,
            flow=flow,
            flow_version=flow_version,
            node=nodes[0],
        )

    async def revoke(
        self,
        *,
        login_user,
        instance_id: int,
        reason: str | None,
    ) -> dict:
        reason = self.normalize_reason(reason)
        try:
            instance = (
                (
                    await self.session.execute(
                        select(ApprovalInstance).where(ApprovalInstance.id == instance_id).with_for_update()
                    )
                )
                .scalars()
                .first()
            )
            if (
                instance is None
                or instance.scenario_code != self.SCENARIO_CODE
                or instance.tenant_id != int(login_user.tenant_id)
            ):
                raise ApprovalRequestNotFoundError()

            payload = instance.payload_snapshot or {}
            space_id = int(payload.get("space_id") or 0)
            file_id = int(payload.get("file_id") or 0)
            department_id = int(payload.get("department_id") or 0)
            file = await self.file_repository.find_by_id_for_update(file_id)
            if file is None or int(getattr(file, "knowledge_id", 0) or 0) != space_id:
                raise ApprovalDepartmentFileInvalidBindingError()
            resource = await self.access_service.load_resource(file)
            if not resource.valid or resource.department_id is None or int(resource.department_id) != department_id:
                raise ApprovalDepartmentFileInvalidBindingError()

            approvers = await self.access_service.resolve_department_approvers(int(resource.department_id))
            is_admin = bool(callable(getattr(login_user, "is_admin", None)) and login_user.is_admin())
            if not is_admin and int(login_user.user_id) not in approvers:
                raise ApprovalRequestPermissionDeniedError()

            grant_repository = self.access_service.grant_repository
            grant = await grant_repository.revoke(
                tenant_id=int(login_user.tenant_id),
                user_id=int(instance.applicant_user_id),
                space_id=space_id,
                file_id=file_id,
                approval_instance_id=int(instance.id),
                revoked_by=int(login_user.user_id),
                reason=reason,
            )
            if grant is None:
                raise ApprovalDepartmentFileGrantNotRevokableError()
            self.session.add(
                ApprovalActionLog(
                    tenant_id=int(login_user.tenant_id),
                    instance_id=int(instance.id),
                    action="revoke_grant",
                    operator_user_id=int(login_user.user_id),
                    operator_user_name=str(login_user.user_name or ""),
                    detail={
                        "reason": reason,
                        "space_id": space_id,
                        "file_id": file_id,
                    },
                )
            )
            DepartmentFileViewGrantAuditWriter(self.session).add_transition(
                grant=grant,
                operator_id=int(login_user.user_id),
                operator_name=str(login_user.user_name or ""),
                action="approval.department_file_view.grant.revoke",
                old_status="active",
                new_status=grant.status,
                reason=reason,
            )
            await self.session.commit()
            return {
                "instance_id": int(instance.id),
                "space_id": space_id,
                "file_id": file_id,
                "grant_status": grant.status,
            }
        except Exception:
            await self.session.rollback()
            raise

    async def _find_latest_instance(
        self,
        *,
        tenant_id: int,
        applicant_user_id: int,
        space_id: int,
        file_id: int,
        statuses: tuple[str, ...] | None = None,
        for_update: bool = False,
    ) -> ApprovalInstance | None:
        statement = (
            select(ApprovalInstance)
            .where(
                ApprovalInstance.tenant_id == tenant_id,
                ApprovalInstance.scenario_code == self.SCENARIO_CODE,
                ApprovalInstance.business_key == f"department-file:{space_id}:{file_id}",
                ApprovalInstance.applicant_user_id == applicant_user_id,
            )
            .order_by(ApprovalInstance.id.desc())
        )
        if statuses:
            statement = statement.where(ApprovalInstance.status.in_(statuses))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalars().first()

    async def _list_tasks(self, instance_id: int) -> list[ApprovalTask]:
        return list(
            (
                await self.session.execute(
                    select(ApprovalTask).where(ApprovalTask.instance_id == instance_id).order_by(ApprovalTask.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _get_applicant_department_id(self, user_id: int) -> int | None:
        row = (
            (
                await self.session.execute(
                    select(UserDepartment)
                    .where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.is_primary == 1,
                    )
                    .order_by(UserDepartment.id.asc())
                )
            )
            .scalars()
            .first()
        )
        return int(row.department_id) if row is not None else None

    @staticmethod
    async def _notify_approvers(
        *,
        applicant_user_id: int,
        applicant_user_name: str,
        approver_user_ids: list[int],
        business_name: str,
        instance_id: int,
        task_ids: list[int],
    ) -> None:
        from bisheng.approval.domain.services.approval_notification_service import (
            ApprovalNotificationService,
        )

        for approver_user_id, task_id in zip(
            approver_user_ids,
            task_ids,
            strict=True,
        ):
            await ApprovalNotificationService.notify_user(
                sender=applicant_user_id,
                receiver_user_id=approver_user_id,
                action_code="approval_task_pending",
                business_name=business_name,
                instance_id=instance_id,
                task_id=task_id,
            )

    @staticmethod
    def _access_payload(
        *,
        space_id: int,
        file_id: int,
        decision,
        status: str,
        access_source: str | None = None,
        safe_metadata: dict | None = None,
        instance: ApprovalInstance | None = None,
    ) -> dict:
        return {
            "space_id": int(space_id),
            "file_id": int(file_id),
            "status": status,
            "content_access": decision.status,
            "access_source": access_source or decision.source,
            "can_download": bool(decision.can_download),
            "instance_id": int(instance.id) if instance is not None else None,
            "latest_instance_status": (instance.status if instance is not None else None),
            "safe_metadata": safe_metadata or {},
        }

    @staticmethod
    def _invalid_status(
        *,
        space_id: int,
        file_id: int,
        can_download: bool = False,
    ) -> dict:
        return {
            "space_id": int(space_id),
            "file_id": int(file_id),
            "status": "invalid_binding",
            "content_access": "unavailable",
            "access_source": None,
            "can_download": bool(can_download),
            "instance_id": None,
            "latest_instance_status": None,
            "safe_metadata": {},
        }

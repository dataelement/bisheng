from __future__ import annotations

from bisheng.common.errcode.approval import (
    ApprovalApproverUnavailableError,
    ApprovalDepartmentFileInvalidBindingError,
)
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)


class DepartmentFileViewApprovalHandler:
    scenario_code = "department_file_view_request"

    async def validate(self, req, login_user) -> None:
        async with get_async_db_session() as session:
            await self._load_live_resource(session=session, req=req)

    async def build_title(self, req) -> str:
        file_name = str(
            (getattr(req, "payload_snapshot", {}) or {}).get("file_name") or getattr(req, "business_name", "") or ""
        )
        return f"查看部门文件: {file_name}"

    async def build_detail(self, req) -> dict:
        payload = getattr(req, "payload_snapshot", {}) or {}
        return {
            "type": "department_file_view",
            "space_id": payload.get("space_id"),
            "file_id": payload.get("file_id"),
            "file_name": payload.get("file_name"),
            "space_name": payload.get("space_name"),
            "department_id": payload.get("department_id"),
            "department_name": payload.get("department_name"),
            "reason": getattr(req, "reason", None),
        }

    async def build_business_link(self, req) -> dict:
        payload = getattr(req, "payload_snapshot", {}) or {}
        return {
            "space_id": payload.get("space_id"),
            "file_id": payload.get("file_id"),
        }

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get("sources") or []
        if sources != [{"type": "department_file_approvers"}]:
            raise ApprovalDepartmentFileInvalidBindingError()
        async with get_async_db_session() as session:
            _, resource, access_service = await self._load_live_resource(
                session=session,
                req=req,
            )
            approvers = sorted(await access_service.resolve_department_approvers(int(resource.department_id)))
        if not approvers:
            raise ApprovalApproverUnavailableError()
        return approvers

    async def on_approved(
        self,
        instance_id: int,
        payload_snapshot: dict,
    ) -> dict:
        async with get_async_db_session() as session:
            try:
                file_repository = KnowledgeFileRepositoryImpl(session)
                file_id = int(payload_snapshot.get("file_id") or 0)
                space_id = int(payload_snapshot.get("space_id") or 0)
                file = await file_repository.find_by_id_for_update(file_id)
                if file is None or int(getattr(file, "knowledge_id", 0) or 0) != space_id:
                    raise ApprovalDepartmentFileInvalidBindingError()

                grant_repository = DepartmentFileViewGrantRepositoryImpl(session)
                access_service = DepartmentFileViewAccessService(
                    session=session,
                    grant_repository=grant_repository,
                )
                resource = await access_service.load_resource(file)
                expected_department_id = int(payload_snapshot.get("department_id") or 0)
                if (
                    not resource.valid
                    or resource.department_id is None
                    or int(resource.department_id) != expected_department_id
                ):
                    raise ApprovalDepartmentFileInvalidBindingError()

                from bisheng.permission.domain.services.department_transfer_grant_guard import (
                    protect_department_file_grant,
                )

                applicant_user_id = int(payload_snapshot.get("applicant_user_id") or 0)
                await protect_department_file_grant(
                    user_id=applicant_user_id,
                    space_id=space_id,
                    file_id=file_id,
                    approval_instance_id=int(instance_id),
                )
                grant = await grant_repository.activate(
                    tenant_id=int(payload_snapshot.get("tenant_id") or 1),
                    user_id=applicant_user_id,
                    space_id=space_id,
                    file_id=file_id,
                    department_id=int(resource.department_id),
                    approval_instance_id=int(instance_id),
                )
                DepartmentFileViewGrantAuditWriter(session).add_transition(
                    grant=grant,
                    operator_id=0,
                    operator_name="system",
                    action="approval.department_file_view.grant.activate",
                    old_status=None,
                    new_status=grant.status,
                    reason="approval_handler",
                )
                await session.commit()
                return {
                    "status": grant.status,
                    "grant_id": int(grant.id),
                }
            except Exception:
                await session.rollback()
                raise

    async def on_rejected(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        return None

    async def on_withdrawn(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        return None

    async def on_cancelled(
        self,
        instance_id: int,
        payload_snapshot: dict,
        reason: str | None,
    ) -> None:
        return None

    @staticmethod
    async def _load_live_resource(*, session, req):
        payload = getattr(req, "payload_snapshot", {}) or {}
        file_id = int(payload.get("file_id") or 0)
        space_id = int(payload.get("space_id") or 0)
        file_repository = KnowledgeFileRepositoryImpl(session)
        file = await file_repository.find_by_id(file_id)
        if file is None or int(getattr(file, "knowledge_id", 0) or 0) != space_id:
            raise ApprovalDepartmentFileInvalidBindingError()
        access_service = DepartmentFileViewAccessService(
            session=session,
            grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
        )
        resource = await access_service.load_resource(file)
        if not resource.valid or resource.department_id is None:
            raise ApprovalDepartmentFileInvalidBindingError()
        return file, resource, access_service

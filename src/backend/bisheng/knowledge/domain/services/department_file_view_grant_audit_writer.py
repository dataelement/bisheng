from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.audit_log import AuditLog
from bisheng.knowledge.domain.models.department_file_view_grant import (
    DepartmentFileViewGrant,
)


class DepartmentFileViewGrantAuditWriter:
    def __init__(self, session: AsyncSession):
        self.session = session

    def add_transition(
        self,
        *,
        grant: DepartmentFileViewGrant,
        operator_id: int,
        action: str,
        old_status: str | None,
        new_status: str,
        reason: str | None,
        operator_name: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            tenant_id=grant.tenant_id,
            operator_id=operator_id,
            operator_name=operator_name,
            operator_tenant_id=grant.tenant_id,
            action=action,
            target_type="department_knowledge_file",
            target_id=str(grant.file_id),
            reason=reason,
            audit_metadata={
                "grant_id": grant.id,
                "user_id": grant.user_id,
                "space_id": grant.space_id,
                "file_id": grant.file_id,
                "department_id": grant.department_id,
                "approval_instance_id": grant.approval_instance_id,
                "old_status": old_status,
                "new_status": new_status,
            },
        )
        self.session.add(row)
        return row

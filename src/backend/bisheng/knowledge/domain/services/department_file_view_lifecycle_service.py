from __future__ import annotations

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError
from bisheng.knowledge.domain.services.department_file_view_grant_audit_writer import (
    DepartmentFileViewGrantAuditWriter,
)


class DepartmentFileViewLifecycleService:
    """在资源写事务内同步维护部门文件审批授权事实与审计证据。"""

    def __init__(
        self,
        *,
        session,
        file_repository,
        grant_repository,
    ) -> None:
        self.session = session
        self.file_repository = file_repository
        self.grant_repository = grant_repository
        self.audit_writer = DepartmentFileViewGrantAuditWriter(session)

    async def prepare_file_delete(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_ids: list[int],
        operator_id: int,
        operator_name: str,
    ) -> None:
        normalized_ids = sorted({int(file_id) for file_id in file_ids})
        if not normalized_ids:
            return
        locked_files = await self.file_repository.find_by_ids_for_update(normalized_ids)
        locked_by_id = {int(file.id): file for file in locked_files}
        if set(locked_by_id) != set(normalized_ids) or any(
            int(file.knowledge_id) != int(space_id) for file in locked_files
        ):
            raise SpaceFileNotFoundError()

        invalidated = await self.grant_repository.invalidate_by_file_ids(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
            file_ids=set(normalized_ids),
            reason="file_deleted",
        )
        for grant in invalidated:
            self.audit_writer.add_transition(
                grant=grant,
                operator_id=int(operator_id),
                operator_name=operator_name,
                action="approval.department_file_view.grant.invalidate",
                old_status="active",
                new_status=grant.status,
                reason="file_deleted",
            )
        await self.file_repository.prepare_delete_by_ids(normalized_ids)

    async def prepare_department_rebind(
        self,
        *,
        tenant_id: int,
        space_id: int,
        old_department_id: int,
        new_department_id: int,
        operator_id: int,
        operator_name: str,
    ) -> None:
        if int(old_department_id) == int(new_department_id):
            return
        invalidated = await self.grant_repository.invalidate_by_space(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
            reason="department_rebound",
        )
        for grant in invalidated:
            self.audit_writer.add_transition(
                grant=grant,
                operator_id=int(operator_id),
                operator_name=operator_name,
                action="approval.department_file_view.grant.invalidate",
                old_status="active",
                new_status=grant.status,
                reason="department_rebound",
            )

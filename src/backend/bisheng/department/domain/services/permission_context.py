"""Supply complete department membership facts without deciding resource access."""

from __future__ import annotations

import asyncio

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.department.domain.repositories.permission_context_repository import DepartmentPermissionContextRepository
from bisheng.permission.application.department_context import ActorDepartmentContext
from bisheng.permission.application.department_recovery import emit_projection_alert


class DepartmentPermissionContextProvider:
    def __init__(self, repository: DepartmentPermissionContextRepository | None = None) -> None:
        self._repository = repository or DepartmentPermissionContextRepository()

    async def load(self, user_id: int) -> ActorDepartmentContext:
        async with asyncio.timeout(5):
            direct, rows = await self._repository.load_ancestry(user_id, limit=100)
        result: set[int] = set()
        for department_id in direct:
            current = department_id
            visited: set[int] = set()
            while current is not None:
                if current in visited or current not in rows:
                    emit_projection_alert(
                        "CONTEXT_REJECTED",
                        reason_code="ANCESTRY_CYCLE_OR_MISSING",
                        tenant_id=rows[department_id].tenant_id if department_id in rows else get_current_tenant_id(),
                        department_id=department_id,
                        details={"ancestor_id": current, "phase": "request_permission_context"},
                    )
                    raise PermissionPublishNotReadyError(msg="Department ancestry is invalid")
                visited.add(current)
                row = rows[current]
                if row.status != "active" or row.projection_state != "CURRENT":
                    reason = (
                        "ANCESTOR_INACTIVE"
                        if row.status != "active"
                        else (
                            "DEPARTMENT_PROJECTING"
                            if row.projection_state == "PROJECTING"
                            else "DEPARTMENT_FAILED_CLOSED"
                            if row.projection_state == "FAILED_CLOSED"
                            else "DEPARTMENT_PROJECTION_STATE_INVALID"
                        )
                    )
                    emit_projection_alert(
                        "CONTEXT_REJECTED",
                        reason_code=reason,
                        tenant_id=rows[department_id].tenant_id,
                        department_id=department_id,
                        details={
                            "ancestor_id": row.id,
                            "ancestor_status": row.status,
                            "ancestor_projection_state": row.projection_state,
                            "phase": "request_permission_context",
                        },
                    )
                    raise PermissionPublishNotReadyError(msg="Department permission facts are not current")
                result.add(current)
                current = row.parent_id
        return ActorDepartmentContext(user_id=user_id, subtree_department_ids=tuple(sorted(result)))

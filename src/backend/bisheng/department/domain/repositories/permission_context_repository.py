"""Bounded organization reads for request-time permission subject facts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, UserDepartment


@dataclass(frozen=True, slots=True)
class DepartmentContextRow:
    id: int
    parent_id: int | None
    tenant_id: int
    status: str
    projection_state: str


class DepartmentPermissionContextRepository:
    async def load_ancestry(self, user_id: int, limit: int) -> tuple[tuple[int, ...], dict[int, DepartmentContextRow]]:
        # Department IDs and user memberships are global identity facts in FGA.
        # Include existing mount edges across tenants, just as the previous
        # child traversal did. Every query is bounded by this user's memberships
        # or their known parent IDs; resource tenant fences remain authoritative.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                direct = tuple(
                    (
                        await session.exec(
                            select(UserDepartment.department_id)
                            .where(UserDepartment.user_id == user_id)
                            .distinct()
                            .limit(limit + 1)
                        )
                    ).all()
                )
                rows: dict[int, DepartmentContextRow] = {}
                pending = set(direct)
                while pending:
                    if len(rows) + len(pending) > limit:
                        raise PermissionPublishNotReadyError(msg="Department context exceeds 100 departments")
                    found = (await session.exec(select(Department).where(Department.id.in_(pending)))).all()
                    if {int(row.id) for row in found} != pending:
                        raise PermissionPublishNotReadyError(msg="Department ancestry is incomplete")
                    for row in found:
                        rows[int(row.id)] = DepartmentContextRow(
                            id=int(row.id),
                            parent_id=row.parent_id,
                            tenant_id=int(row.tenant_id),
                            status=row.status,
                            projection_state=row.permission_projection_state,
                        )
                    pending = {row.parent_id for row in found if row.parent_id is not None} - rows.keys()
        return direct, rows

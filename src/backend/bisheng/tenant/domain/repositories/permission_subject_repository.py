"""Bounded business-owned names for a verified tenant's authorization summary."""

from sqlmodel import col, select

from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.group import Group
from bisheng.department.application.directory import department_display_records


class PermissionSubjectRepository:
    async def load(self, tenant_id, subjects):
        departments = await department_display_records(
            tenant_id, [int(ident) for typ, ident in subjects if typ == "department"]
        )
        result = {("department", str(row.id)): row for row in departments.values() if row.status == "active"}
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                for kind, model in (("user_group", Group),):
                    ids = tuple({int(ident) for typ, ident in subjects if typ == kind})
                    for offset in range(0, len(ids), 500):
                        rows = (
                            await session.exec(select(model).where(col(model.id).in_(ids[offset : offset + 500])))
                        ).all()
                        for row in rows:
                            if row.tenant_id == tenant_id and getattr(row, "status", "active") == "active":
                                result[(kind, str(row.id))] = row
        return result

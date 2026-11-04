"""Bounded business-owned names for a verified tenant's authorization summary."""

from sqlmodel import col, select

from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.group import Group


class PermissionSubjectRepository:
    async def load(self, tenant_id, subjects):
        result = {}
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                for kind, model in (("department", Department), ("user_group", Group)):
                    ids = tuple({int(ident) for typ, ident in subjects if typ == kind})
                    for offset in range(0, len(ids), 500):
                        rows = (
                            await session.exec(select(model).where(col(model.id).in_(ids[offset : offset + 500])))
                        ).all()
                        for row in rows:
                            if row.tenant_id == tenant_id and getattr(row, "status", "active") == "active":
                                result[(kind, str(row.id))] = row
        return result

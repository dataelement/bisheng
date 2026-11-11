"""Bounded read-only inventory; never converts ambiguous historical rows."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, strict_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.tenant import UserTenant
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.tool.domain.models.gpts_tools import GptsToolsType


class ManagedTenantPreflightRepository:
    @staticmethod
    async def inventory(tenant_id, user_ids, limit=100):
        if tenant_id < 1 or not 1 <= limit <= 1000:
            raise ValueError("tenant_id and bounded limit are required")
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(UserTenant.user_id).where(UserTenant.is_active == 1)
                if user_ids:
                    statement = statement.where(UserTenant.user_id.in_(user_ids))
                else:
                    statement = statement.where(UserTenant.tenant_id == tenant_id)
                users = sorted(set((await session.exec(statement.order_by(UserTenant.user_id).limit(limit + 1))).all()))
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                resources = []
                truncated = {}
                for model, kind in [(Flow, "workflow"), (GptsToolsType, "tool")]:
                    statement = select(model).where(model.tenant_id == tenant_id, model.is_delete == 0)
                    if kind == "workflow":
                        statement = statement.where(Flow.flow_type == 10)
                    if user_ids:
                        statement = statement.where(model.user_id.in_(user_ids))
                    rows = (await session.exec(statement.order_by(model.id).limit(limit + 1))).all()
                    truncated[kind] = len(rows) > limit
                    resources.extend(
                        {"type": kind, "id": str(row.id), "owner_id": row.user_id, "creation_state": row.creation_state}
                        for row in rows[:limit]
                    )
                statement = select(Knowledge).where(Knowledge.tenant_id == tenant_id)
                if user_ids:
                    statement = statement.where(Knowledge.user_id.in_(user_ids))
                copies = (
                    await session.exec(
                        statement.where(
                            (Knowledge.copy_source_id.is_not(None))
                            | (Knowledge.copy_target_id.is_not(None))
                            | (Knowledge.state == KnowledgeState.COPYING.value)
                        )
                        .order_by(Knowledge.id)
                        .limit(limit + 1)
                    )
                ).all()
                return {
                    "tenant_id": tenant_id,
                    "users": users[:limit],
                    "users_truncated": len(users) > limit,
                    "resources": resources,
                    "resources_truncated": truncated,
                    "copy_links": [
                        {
                            "id": row.id,
                            "state": row.state,
                            "source_id": row.copy_source_id,
                            "target_id": row.copy_target_id,
                            "association": "LINKED"
                            if row.copy_source_id or row.copy_target_id
                            else "UNKNOWN_LEGACY_COPYING",
                        }
                        for row in copies[:limit]
                    ],
                    "copy_links_truncated": len(copies) > limit,
                }

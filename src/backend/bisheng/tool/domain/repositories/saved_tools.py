"""Exact saved-tool name lookup within the invoking tenant."""

from sqlmodel import select

from bisheng.core.context.tenant import set_admin_scope_tenant_id, set_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType


class SavedToolRepository:
    @staticmethod
    async def load_by_name(tenant_id: int, name: str) -> tuple[GptsTools | None, GptsToolsType | None]:
        tenant_token = set_current_tenant_id(tenant_id)
        admin_token = set_admin_scope_tenant_id(None)
        try:
            with strict_tenant_filter():
                async with get_async_db_session() as session:
                    result = await session.exec(
                        select(GptsTools).where(GptsTools.name == name, GptsTools.is_delete == 0)
                    )
                    # Keep uniqueness tenant-local even when automatic filtering is bypassed.
                    matches = [tool for tool in result.all() if tool.tenant_id == tenant_id and tool.name == name]
                    if len(matches) != 1:
                        return None, None
                    tool = matches[0]
                    result = await session.exec(select(GptsToolsType).where(GptsToolsType.id == tool.type))
                    return tool, result.first()
        finally:
            admin_token.var.reset(admin_token)
            tenant_token.var.reset(tenant_token)

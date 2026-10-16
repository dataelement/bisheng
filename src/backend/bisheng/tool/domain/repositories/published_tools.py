"""Load saved tool/category as one tenant-filtered snapshot."""

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.dsh import DshToolServiceUnavailableError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType


class PublishedToolRepository:
    async def snapshot(self, tool_id):
        try:
            return await self._snapshot(tool_id)
        except SQLAlchemyError:
            raise DshToolServiceUnavailableError() from None

    async def _snapshot(self, tool_id):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                row = (
                    await session.exec(
                        select(GptsTools, GptsToolsType)
                        .join(GptsToolsType, GptsTools.type == GptsToolsType.id)
                        .where(GptsTools.id == tool_id)
                    )
                ).first()
                return tuple(row) if row else (None, None)

"""Bounded space-list reads, with the connection released before permission I/O."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeSpaceListingRepository:
    def __init__(self, session_factory: SessionFactory | None = None):
        self._session_factory = session_factory or get_async_db_session

    async def list_spaces(
        self, space_ids: list[int] | None, order_by: str = "name", *, keyword: str | None = None
    ) -> list[Knowledge]:
        """Load a visible set in database order; None is for full-scope admins.

        IN groups stay below DM8's limit. A single ORDER BY preserves the
        existing database collation across groups. Even a global admin's
        result stays inside the current tenant.
        """
        if space_ids is not None and not space_ids:
            return []
        statement = select(Knowledge).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if keyword:
            statement = statement.where(
                or_(col(Knowledge.name).like(f"%{keyword}%"), col(Knowledge.description).like(f"%{keyword}%"))
            )
        if space_ids is not None:
            statement = statement.where(
                or_(*(Knowledge.id.in_(space_ids[offset : offset + 500]) for offset in range(0, len(space_ids), 500)))
            )
        if order_by == "create_time":
            statement = statement.order_by(Knowledge.create_time.desc(), Knowledge.id.desc())
        elif order_by == "name":
            statement = statement.order_by(Knowledge.name.asc(), Knowledge.id.asc())
        else:
            statement = statement.order_by(Knowledge.update_time.desc(), Knowledge.id.desc())
        with strict_tenant_filter():
            async with self._session_factory() as session:
                return list((await session.exec(statement)).all())

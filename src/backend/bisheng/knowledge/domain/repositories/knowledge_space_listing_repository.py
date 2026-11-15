"""Bounded space-list reads, with the connection released before permission I/O."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from sqlalchemy import and_, case, func
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import ABNORMAL_FILE_STATUSES, FileType, KnowledgeFile

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeSpaceListingRepository:
    def __init__(self, session_factory: SessionFactory | None = None):
        self._session_factory = session_factory or get_async_db_session

    @staticmethod
    def _abnormal_exists():
        return (
            select(KnowledgeFile.id)
            .where(
                KnowledgeFile.knowledge_id == Knowledge.id,
                KnowledgeFile.tenant_id == Knowledge.tenant_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status.in_(sorted(ABNORMAL_FILE_STATUSES)),
            )
            .exists()
        )

    @staticmethod
    def _statement(keyword: str | None, has_abnormal: bool | None = None, *, name_only: bool = False):
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0:
            raise ValueError("space lists require a concrete tenant")
        statement = select(Knowledge).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if has_abnormal is True:
            statement = statement.where(KnowledgeSpaceListingRepository._abnormal_exists())
        if keyword and name_only:
            literal = keyword.lower().replace("/", "//").replace("%", "/%").replace("_", "/_")
            statement = statement.where(func.lower(Knowledge.name).like(f"%{literal}%", escape="/"))
        elif keyword:
            statement = statement.where(
                or_(col(Knowledge.name).like(f"%{keyword}%"), col(Knowledge.description).like(f"%{keyword}%"))
            )
        return statement

    @staticmethod
    def _ordered(statement):
        # Explicit NULL placement is consistent on MySQL, DM8 and old SQLite fixtures.
        return statement.order_by(
            case((Knowledge.update_time.is_(None), 1), else_=0), Knowledge.update_time.desc(), Knowledge.id.desc()
        )

    async def alist_candidates(
        self,
        *,
        keyword: str | None = None,
        after: tuple[datetime | None, int] | None = None,
        limit: int = 100,
        has_abnormal: bool | None = None,
        name_only: bool = False,
    ) -> list[Knowledge]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("candidate batches contain 1..100 rows")
        statement = self._statement(keyword, has_abnormal, name_only=name_only)
        if after is not None:
            timestamp, ident = after
            if type(ident) is not int or ident <= 0 or (timestamp is not None and not isinstance(timestamp, datetime)):
                raise ValueError("invalid candidate seek key")
            if timestamp is None:
                statement = statement.where(Knowledge.update_time.is_(None), Knowledge.id < ident)
            else:
                statement = statement.where(
                    or_(
                        Knowledge.update_time < timestamp,
                        and_(Knowledge.update_time == timestamp, Knowledge.id < ident),
                        Knowledge.update_time.is_(None),
                    )
                )
        with strict_tenant_filter():
            async with self._session_factory() as session:
                return list((await session.exec(self._ordered(statement).limit(limit))).all())

    async def alist_admin(
        self, *, keyword: str | None = None, page: int = 1, page_size: int = 20, has_abnormal: bool | None = None
    ) -> tuple[list[Knowledge], int]:
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("invalid admin pagination")
        statement = self._statement(keyword, has_abnormal)
        with strict_tenant_filter():
            async with self._session_factory() as session:
                total = (await session.exec(statement.with_only_columns(func.count(Knowledge.id)))).one()
                rows = (
                    await session.exec(self._ordered(statement).offset((page - 1) * page_size).limit(page_size))
                ).all()
                return list(rows), int(total)

    async def aexists_abnormal_files(self, *, space_ids: list[int]) -> set[int]:
        """Read the final response page once; never enumerate its file rows."""
        if len(space_ids) > 200 or any(type(ident) is not int or ident <= 0 for ident in space_ids):
            raise ValueError("abnormal markers require at most 200 positive space IDs")
        if not space_ids:
            return set()
        statement = self._statement(None, True).with_only_columns(Knowledge.id).where(Knowledge.id.in_(space_ids))
        with strict_tenant_filter():
            async with self._session_factory() as session:
                return set((await session.exec(statement)).all())

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

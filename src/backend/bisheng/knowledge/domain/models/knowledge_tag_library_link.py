"""Many-to-many link between knowledge spaces and tag libraries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, UniqueConstraint, delete, func, text
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeTagLibraryLinkBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    knowledge_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="Knowledge space ID"),
    )
    tag_library_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="Tag library ID"),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
            comment="Merge order for auto-tag candidates",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )


class KnowledgeTagLibraryLink(KnowledgeTagLibraryLinkBase, table=True):
    __tablename__ = "knowledge_tag_library_link"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_id",
            "tag_library_id",
            name="uk_knowledge_tag_library",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)


class KnowledgeTagLibraryLinkDao:
    @classmethod
    async def alist_library_ids_by_knowledge(cls, knowledge_id: int) -> list[int]:
        statement = (
            select(KnowledgeTagLibraryLink.tag_library_id)
            .where(KnowledgeTagLibraryLink.knowledge_id == knowledge_id)
            .order_by(
                KnowledgeTagLibraryLink.sort_order.asc(),
                KnowledgeTagLibraryLink.id.asc(),
            )
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return [int(row) for row in rows]

    @classmethod
    def list_library_ids_by_knowledge(cls, knowledge_id: int) -> list[int]:
        from bisheng.core.database import get_sync_db_session

        statement = (
            select(KnowledgeTagLibraryLink.tag_library_id)
            .where(KnowledgeTagLibraryLink.knowledge_id == knowledge_id)
            .order_by(
                KnowledgeTagLibraryLink.sort_order.asc(),
                KnowledgeTagLibraryLink.id.asc(),
            )
        )
        with get_sync_db_session() as session:
            rows = session.exec(statement).all()
        return [int(row) for row in rows]

    @classmethod
    async def areplace_for_knowledge(
        cls,
        knowledge_id: int,
        tenant_id: int | None,
        library_ids: list[int],
    ) -> None:
        unique_ids = list(dict.fromkeys(int(library_id) for library_id in library_ids if library_id))
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeTagLibraryLink).where(
                    col(KnowledgeTagLibraryLink.knowledge_id) == knowledge_id,
                )
            )
            for index, library_id in enumerate(unique_ids):
                session.add(
                    KnowledgeTagLibraryLink(
                        tenant_id=tenant_id,
                        knowledge_id=knowledge_id,
                        tag_library_id=library_id,
                        sort_order=index,
                    )
                )
            await session.commit()

    @classmethod
    async def acount_by_library(cls, library_id: int) -> int:
        statement = select(func.count(KnowledgeTagLibraryLink.id)).where(
            KnowledgeTagLibraryLink.tag_library_id == library_id,
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def acount_bound_knowledge_spaces(cls, library_id: int) -> int:
        """Count distinct knowledge spaces referencing this library."""
        return len(await cls.alist_bound_space_ids(library_id))

    @classmethod
    async def alist_bound_space_names(cls, library_id: int) -> list[str]:
        """Return ordered knowledge-space names bound to this tag library."""
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        ordered_ids = await cls.alist_bound_space_ids(library_id)
        if not ordered_ids:
            return []

        async with get_async_db_session() as session:
            rows = (await session.exec(select(Knowledge.id, Knowledge.name).where(Knowledge.id.in_(ordered_ids)))).all()

        name_by_id = {int(row[0]): (row[1] or "").strip() for row in rows}
        return [name_by_id[knowledge_id] for knowledge_id in ordered_ids if name_by_id.get(knowledge_id)]

    @classmethod
    async def alist_bound_space_ids(cls, library_id: int) -> list[int]:
        """Knowledge spaces bound to this library, in each space's own order."""
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeTagLibraryLink.knowledge_id)
                    .where(KnowledgeTagLibraryLink.tag_library_id == library_id)
                    .order_by(
                        KnowledgeTagLibraryLink.sort_order.asc(),
                        KnowledgeTagLibraryLink.id.asc(),
                    )
                )
            ).all()
        return list(dict.fromkeys(int(row) for row in rows))

    @classmethod
    async def aadd_links(
        cls,
        library_id: int,
        knowledge_ids: list[int],
        tenant_id: int | None = None,
    ) -> list[int]:
        """Attach spaces to this library, skipping ones already attached.

        sort_order here is the space's own merge order over its libraries, not
        the admin list order, so a newly attached library goes on the end of
        whatever that space already had.
        """
        wanted = list(dict.fromkeys(int(kid) for kid in knowledge_ids if kid))
        if not wanted:
            return []

        added: list[int] = []
        async with get_async_db_session() as session:
            existing = {
                int(row)
                for row in (
                    await session.exec(
                        select(KnowledgeTagLibraryLink.knowledge_id).where(
                            KnowledgeTagLibraryLink.tag_library_id == library_id,
                            col(KnowledgeTagLibraryLink.knowledge_id).in_(wanted),
                        )
                    )
                ).all()
            }
            for knowledge_id in wanted:
                if knowledge_id in existing:
                    continue
                next_order = (
                    await session.scalar(
                        select(func.max(KnowledgeTagLibraryLink.sort_order)).where(
                            KnowledgeTagLibraryLink.knowledge_id == knowledge_id,
                        )
                    )
                    or 0
                )
                session.add(
                    KnowledgeTagLibraryLink(
                        tenant_id=tenant_id,
                        knowledge_id=knowledge_id,
                        tag_library_id=library_id,
                        sort_order=int(next_order) + 1,
                    )
                )
                added.append(knowledge_id)
            await session.commit()
        return added

    @classmethod
    async def aremove_link(cls, library_id: int, knowledge_id: int) -> None:
        """Detach one space from this library.

        Losing the last library no longer turns auto-tagging off: unbound
        spaces can still pick tags from other public libraries.
        """
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeTagLibraryLink).where(
                    col(KnowledgeTagLibraryLink.tag_library_id) == int(library_id),
                    col(KnowledgeTagLibraryLink.knowledge_id) == int(knowledge_id),
                )
            )
            await session.commit()

    @classmethod
    async def adelete_by_library(cls, library_id: int) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeTagLibraryLink).where(
                    col(KnowledgeTagLibraryLink.tag_library_id) == library_id,
                )
            )
            await session.commit()

    @classmethod
    async def adelete_by_knowledge(cls, knowledge_id: int) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeTagLibraryLink).where(
                    col(KnowledgeTagLibraryLink.knowledge_id) == knowledge_id,
                )
            )
            await session.commit()

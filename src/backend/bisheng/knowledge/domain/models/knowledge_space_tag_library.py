from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    func,
    text,
    update,
    delete,
)
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import JsonType, UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceTagLibraryBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    name: str = Field(
        sa_column=Column(String(200), nullable=False, index=True, comment="标签库名称")
    )
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(String(1000), nullable=True, comment="标签库说明"),
    )
    tags: List[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False, comment="标签列表"),
    )
    tag_count: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="标签数量"
        ),
    )
    ai_tags: List[str] = Field(
        default_factory=list,
        sa_column=Column(JsonType, nullable=False, comment="AI生成的标签列表"),
    )
    ai_tag_count: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="AI生成的标签数量"
        ),
    )
    is_builtin: bool = Field(
        default=False,
        sa_column=Column(
            Boolean, nullable=False, server_default=text("0"), comment="是否内置标签库"
        ),
    )
    owner_knowledge_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=True,
            index=True,
            comment="拥有该私有库的知识空间ID; NULL 表示租户公共库",
        ),
    )
    user_id: int = Field(
        default=0,
        sa_column=Column(
            Integer, nullable=False, server_default=text("0"), comment="创建人ID"
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT
        ),
    )


class KnowledgeSpaceTagLibrary(KnowledgeSpaceTagLibraryBase, table=True):
    __tablename__ = "knowledge_space_tag_library"

    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeSpaceTagLibraryDao:
    @classmethod
    async def acount(cls, keyword: Optional[str] = None) -> int:
        statement = select(func.count(KnowledgeSpaceTagLibrary.id)).where(
            KnowledgeSpaceTagLibrary.owner_knowledge_id.is_(None)
        )
        if keyword:
            statement = statement.where(
                KnowledgeSpaceTagLibrary.name.like(f"%{keyword}%")
            )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def alist(
        cls, page: int = 1, page_size: int = 20, keyword: Optional[str] = None
    ) -> List[KnowledgeSpaceTagLibrary]:
        statement = select(KnowledgeSpaceTagLibrary).where(
            KnowledgeSpaceTagLibrary.owner_knowledge_id.is_(None)
        )
        if keyword:
            statement = statement.where(
                KnowledgeSpaceTagLibrary.name.like(f"%{keyword}%")
            )
        statement = statement.order_by(KnowledgeSpaceTagLibrary.id.desc())
        if page > 0 and page_size > 0:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        async with get_async_db_session() as session:
            return (await session.exec(statement)).all()

    @classmethod
    async def aget(cls, library_id: int) -> Optional[KnowledgeSpaceTagLibrary]:
        async with get_async_db_session() as session:
            return (
                await session.exec(
                    select(KnowledgeSpaceTagLibrary).where(
                        KnowledgeSpaceTagLibrary.id == library_id
                    )
                )
            ).first()

    @classmethod
    def get(cls, library_id: int) -> Optional[KnowledgeSpaceTagLibrary]:
        with get_sync_db_session() as session:
            return session.exec(
                select(KnowledgeSpaceTagLibrary).where(
                    KnowledgeSpaceTagLibrary.id == library_id
                )
            ).first()

    @classmethod
    async def ainsert(cls, data: KnowledgeSpaceTagLibrary) -> KnowledgeSpaceTagLibrary:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def aupdate(
        cls, library_id: int, **kwargs
    ) -> Optional[KnowledgeSpaceTagLibrary]:
        async with get_async_db_session() as session:
            data = (
                await session.exec(
                    select(KnowledgeSpaceTagLibrary).where(
                        KnowledgeSpaceTagLibrary.id == library_id
                    )
                )
            ).first()
            if not data:
                return None
            for key, value in kwargs.items():
                setattr(data, key, value)
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def adelete(cls, library_id: int) -> bool:
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeSpaceTagLibrary).where(
                    col(KnowledgeSpaceTagLibrary.id) == library_id
                )
            )
            await session.commit()
            return True

    @classmethod
    async def acount_used_by_spaces(cls, library_id: int) -> int:
        """Count knowledge spaces that have this library bound (tenant-filtered by SELECT).

        Used by the pre-delete confirmation flow to tell the admin how many spaces
        will lose their auto-tag binding if they proceed.
        """
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        statement = select(func.count(Knowledge.id)).where(
            Knowledge.auto_tag_library_id == library_id
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    async def aclear_space_bindings(cls, library_id: int) -> None:
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        async with get_async_db_session() as session:
            library = (
                await session.exec(
                    select(KnowledgeSpaceTagLibrary).where(
                        KnowledgeSpaceTagLibrary.id == library_id
                    )
                )
            ).first()
            if not library:
                return
            await session.exec(
                update(Knowledge)
                .where(Knowledge.auto_tag_library_id == library_id)
                .where(Knowledge.tenant_id == library.tenant_id)
                .values(auto_tag_enabled=False, auto_tag_library_id=None)
            )
            await session.commit()

    @classmethod
    async def aget_private_for_knowledge(
        cls, knowledge_id: int
    ) -> Optional[KnowledgeSpaceTagLibrary]:
        async with get_async_db_session() as session:
            return (
                await session.exec(
                    select(KnowledgeSpaceTagLibrary).where(
                        KnowledgeSpaceTagLibrary.owner_knowledge_id == knowledge_id
                    )
                )
            ).first()

    @classmethod
    async def aupsert_private(
        cls,
        knowledge_id: int,
        tenant_id: Optional[int],
        user_id: int,
        tags: List[str],
    ) -> KnowledgeSpaceTagLibrary:
        """Insert or update the private tag library bound to ``knowledge_id``.

        Private libraries are 1:1 with a knowledge space, hidden from the
        admin-facing list. The auto-tag service reads them like any other
        library, so changing tags here is enough — no extra wiring required.
        """
        normalized = list(tags)
        async with get_async_db_session() as session:
            existing = (
                await session.exec(
                    select(KnowledgeSpaceTagLibrary).where(
                        KnowledgeSpaceTagLibrary.owner_knowledge_id == knowledge_id
                    )
                )
            ).first()
            if existing:
                existing.tags = normalized
                existing.tag_count = len(normalized)
                if tenant_id is not None and existing.tenant_id != tenant_id:
                    existing.tenant_id = tenant_id
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
                return existing

            row = KnowledgeSpaceTagLibrary(
                tenant_id=tenant_id,
                name=f"__private__{knowledge_id}",
                description=None,
                tags=normalized,
                tag_count=len(normalized),
                is_builtin=False,
                user_id=user_id or 0,
                owner_knowledge_id=knowledge_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def adelete_private_for_knowledge(cls, knowledge_id: int) -> None:
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeSpaceTagLibrary).where(
                    col(KnowledgeSpaceTagLibrary.owner_knowledge_id) == knowledge_id
                )
            )
            await session.commit()

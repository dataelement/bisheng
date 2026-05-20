from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    func,
    select,
    text,
    update,
    delete,
)
from sqlmodel import Field, col

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
    is_builtin: bool = Field(
        default=False,
        sa_column=Column(
            Boolean, nullable=False, server_default=text("0"), comment="是否内置标签库"
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
        statement = select(func.count(KnowledgeSpaceTagLibrary.id))
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
        statement = select(KnowledgeSpaceTagLibrary)
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
    async def aclear_space_bindings(cls, library_id: int) -> None:
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        async with get_async_db_session() as session:
            await session.exec(
                update(Knowledge)
                .where(Knowledge.auto_tag_library_id == library_id)
                .values(auto_tag_enabled=False, auto_tag_library_id=None)
            )
            await session.commit()

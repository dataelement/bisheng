from datetime import datetime
from typing import Any, List, Optional, Tuple

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, and_, text
from sqlmodel import Field, select


class KnowledgeBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(index=True)
    model: Optional[str] = Field(index=False)
    collection_name: Optional[str] = Field(index=False)
    index_name: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Knowledge(KnowledgeBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeRead(KnowledgeBase):
    id: int
    user_name: Optional[str]


class KnowledgeUpdate(KnowledgeBase):
    id: int
    name: str


class KnowledgeCreate(KnowledgeBase):
    is_partition: Optional[bool] = None


class KnowledgeDao(KnowledgeBase):
    from bisheng.database.models.role_access import RoleAccess

    @classmethod
    def query_by_id(cls, id: int) -> Knowledge:
        with session_getter() as session:
            return session.get(Knowledge, id)

    @classmethod
    def get_list_by_ids(cls, ids: List[int]):
        with session_getter() as session:
            return session.exec(select(Knowledge).where(Knowledge.id.in_(ids))).all()

    @classmethod
    def get_knowledge_by_access(role_id: int, name: str, page_size: int,
                                page_num: int) -> List[Tuple[Knowledge, RoleAccess]]:
        from bisheng.database.models.role_access import RoleAccess, AccessType
        statment = select(Knowledge,
                          RoleAccess).join(RoleAccess,
                                           and_(RoleAccess.role_id == role_id,
                                                RoleAccess.type == AccessType.KNOWLEDGE.value,
                                                RoleAccess.third_id == Knowledge.id),
                                           isouter=True)
        if name:
            statment = statment.where(Knowledge.name.like('%' + name + '%'))
        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            statment = statment.order_by(RoleAccess.type.desc()).order_by(
                Knowledge.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)
        with session_getter() as session:
            return session.exec(statment).all()

    @classmethod
    def get_count_by_filter(cls, filters: List[Any]) -> int:
        with session_getter() as session:
            return session.scalar(select(Knowledge.id).where(*filters))

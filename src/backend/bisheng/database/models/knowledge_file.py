from datetime import datetime
from typing import Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field, func


class KnowledgeFileBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    knowledge_id: int = Field(index=True)
    file_name: str = Field(index=True)
    md5: Optional[str] = Field(index=False)
    status: Optional[int] = Field(index=False)
    object_name: Optional[str] = Field(index=False)
    extra_meta: Optional[str] = Field(index=False)
    remark: Optional[str] = Field(sa_column=Column(String(length=512)))
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class KnowledgeFile(KnowledgeFileBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeFileRead(KnowledgeFileBase):
    id: int


class KnowledgeFileCreate(KnowledgeFileBase):
    pass


class KnowledgeFileDao(KnowledgeFileBase):

    @classmethod
    def get_file_simple_by_knowledge_id(cls, knowledge_id: int, page: int, page_size: int):
        offset = (page - 1) * page_size
        with session_getter() as session:
            return session.query(
                KnowledgeFile.id, KnowledgeFile.object_name
            ).filter(
                KnowledgeFile.knowledge_id == knowledge_id
            ).order_by(
                KnowledgeFile.id.asc()
            ).offset(offset).limit(page_size).all()

    @classmethod
    def count_file_by_knowledge_id(cls, knowledge_id: int):
        with session_getter() as session:
            return session.query(
                func.count(KnowledgeFile.id)
            ).filter(
                KnowledgeFile.knowledge_id == knowledge_id
            ).scalar()

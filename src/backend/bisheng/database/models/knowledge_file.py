from datetime import datetime
from enum import Enum
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field, delete, func, select


class KnowledgeFileStatus(Enum):
    PROCESSING = 1
    SUCCESS = 2
    FAILED = 3


class ParseType(Enum):
    LOCAL = 'local'  # 本地模式解析
    UNS = 'uns'  # uns服务解析，全部转为pdf文件


class KnowledgeFileBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True)
    knowledge_id: int = Field(index=True)
    file_name: str = Field(index=True)
    md5: Optional[str] = Field(index=False)
    parse_type: Optional[str] = Field(default=ParseType.LOCAL.value, index=False, description="采用什么模式解析的文件")
    bbox_object_name: Optional[str] = Field(default='', description="bbox文件在minio存储的对象名称")
    status: Optional[int] = Field(default=KnowledgeFileStatus.PROCESSING.value,
                                  index=False, description="1: 解析中；2: 解析成功；3: 解析失败")
    object_name: Optional[str] = Field(index=False)
    extra_meta: Optional[str] = Field(index=False)
    remark: Optional[str] = Field(default='', sa_column=Column(String(length=512)))
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
            return session.query(KnowledgeFile.id, KnowledgeFile.object_name).filter(
                KnowledgeFile.knowledge_id == knowledge_id).order_by(
                KnowledgeFile.id.asc()).offset(offset).limit(page_size).all()

    @classmethod
    def count_file_by_knowledge_id(cls, knowledge_id: int):
        with session_getter() as session:
            return session.query(func.count(
                KnowledgeFile.id)).filter(KnowledgeFile.knowledge_id == knowledge_id).scalar()

    @classmethod
    def delete_batch(cls, file_ids: List[int]) -> bool:
        with session_getter() as session:
            session.exec(delete(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
            session.commit()
            return True

    @classmethod
    def add_file(cls, knowledge_file: KnowledgeFile) -> KnowledgeFile:
        with session_getter() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    def update(cls, knowledge_file):
        with session_getter() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        return knowledge_file

    @classmethod
    def get_file_by_condition(cls, knowledge_id: int, md5_: str = None, file_name: str = None):
        with session_getter() as session:
            sql = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)
            if md5_:
                sql = sql.where(KnowledgeFile.md5 == md5_)
            if file_name:
                sql = sql.where(KnowledgeFile.file_name == file_name)
            return session.exec(sql).all()

    @classmethod
    def select_list(cls, file_ids: List[int]):
        if not file_ids:
            return []
        with session_getter() as session:
            knowledge_files = session.exec(
                select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()
        if not knowledge_files:
            raise ValueError('文件ID不存在')
        return knowledge_files

    @classmethod
    def get_file_by_ids(cls, file_ids: List[int]):
        if not file_ids:
            return []
        with session_getter() as session:
            return session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()

    @classmethod
    def get_file_by_filters(cls, knowledge_id: int, file_name: str = None, status: int = None,
                            page: int = 0, page_size: int = 0) -> List[KnowledgeFile]:
        statement = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        if status is not None:
            statement = statement.where(KnowledgeFile.status == status)
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        statement = statement.order_by(KnowledgeFile.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_file_by_filters(cls, knowledge_id: int, file_name: str = None, status: int = None) -> int:
        statement = select(func.count(KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id)
        if file_name:
            statement = statement.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        if status is not None:
            statement = statement.where(KnowledgeFile.status == status)
        with session_getter() as session:
            return session.scalar(statement)

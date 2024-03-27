from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from numpy import integer
from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field, null, or_, select


class GptsToolsBase(SQLModelSerializable):
    name: str = Field(sa_column=Column(String(length=125), index=True))
    logo: Optional[str] = Field(sa_column=Column(String(length=512), index=False))
    desc: Optional[str] = Field(sa_column=Column(String(length=2048), index=False))
    tool_key: str = Field(sa_column=Column(String(length=125), index=False))
    type: integer = Field(default=0, description='表示工具是技能组装还是原生工具，type=1 表示技能')
    extra: Optional[str] = Field(sa_column=Column(String(length=2048), index=False),
                                 description='用来存储额外信息，比如参数需求等')
    is_preset: bool = Field(default=True)
    is_delete: int = Field(default=0, description='1 表示逻辑删除')
    user_id: Optional[int] = Field(index=True)
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class GptsTools(GptsToolsBase, table=True):
    __tablename__ = 't_gpts_tools'
    id: Optional[int] = Field(default=None, primary_key=True)


class GptsToolsDao(GptsToolsBase):

    @classmethod
    def insert(cls, obj: GptsTools):
        with session_getter() as session:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    @classmethod
    def query_by_name(cls, name: str) -> List[GptsTools]:
        with session_getter() as session:
            statement = select(GptsTools).where(GptsTools.name.like(f'%{name}%'))
            return session.exec(statement).all()

    @classmethod
    def update_tools(cls, data: GptsTools) -> GptsTools:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete_tool(cls, data: GptsTools) -> GptsTools:
        data.is_delete = 1
        return cls.update_tools(data)

    @classmethod
    def get_one_tool(cls, tool_id: int) -> GptsTools:
        with session_getter() as session:
            statement = select(GptsTools).where(GptsTools.id == tool_id)
            return session.exec(statement).first()

    @classmethod
    def get_list_by_ids(cls, tool_ids: List[int]) -> List[GptsTools]:
        with session_getter() as session:
            statement = select(GptsTools).where(GptsTools.id.in_(tool_ids))
            return session.exec(statement).all()

    @classmethod
    def get_list_by_user(cls, user_id: int) -> List[GptsTools]:
        with session_getter() as session:
            statement = select(GptsTools).where(
                or_(GptsTools.user_id == user_id, GptsTools.user_id is null))
            return session.exec(statement).all()

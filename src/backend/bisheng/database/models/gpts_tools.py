from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import JSON, Column, DateTime, String, text
from sqlmodel import Field, or_, select


class AuthMethod(Enum):
    NO = 0
    API_KEY = 1


class AuthType(Enum):
    BASIC = "basic"
    BEARER = "bearer"


class GptsToolsBase(SQLModelSerializable):
    name: str = Field(sa_column=Column(String(length=125), index=True))
    logo: Optional[str] = Field(sa_column=Column(String(length=512), index=False))
    desc: Optional[str] = Field(sa_column=Column(String(length=2048), index=False))
    tool_key: str = Field(sa_column=Column(String(length=125), index=False))
    type: int = Field(default=0, description='所属类别的ID')
    is_preset: bool = Field(default=True)
    is_delete: int = Field(default=0, description='1 表示逻辑删除')
    api_params: Optional[List[Dict]] = Field(sa_column=Column(JSON), description='用来存储api参数等信息')
    user_id: Optional[int] = Field(index=True, description='创建用户ID， null表示系统创建')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class GptsToolsTypeBase(SQLModelSerializable):
    id: Optional[int] = Field(index=True, primary_key=True)
    name: str = Field(default='', index=True, description="工具类别名字")
    logo: Optional[str] = Field(default='', description="工具类别的logo文件地址")
    description: str = Field(default='', description="工具类别的描述")
    auth_method: Optional[int] = Field(default=0, description="工具类别的鉴权方式")
    api_key: Optional[str] = Field(default='', description="工具鉴权的api_key")
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description="工具鉴权的鉴权方式")
    is_preset: Optional[int] = Field(default=True, description="是否是预置工具类别")
    user_id: Optional[int] = Field(index=True, description='创建用户ID， null表示系统创建')
    is_delete: int = Field(default=0, description='1 表示逻辑删除')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class GptsTools(GptsToolsBase, table=True):
    __tablename__ = 't_gpts_tools'
    extra: Optional[str] = Field(sa_column=Column(String(length=2048), index=False),
                                 description='用来存储额外信息，比如参数需求等，包含 &initdb_conf_key 字段'
                                             '表示配置信息从系统配置里获取,多层级用.隔开')
    id: Optional[int] = Field(default=None, primary_key=True)


class GptsToolsType(GptsToolsTypeBase, table=True):
    __tablename__ = 't_gpts_tools_type'
    openapi_schema: Dict = Field(default=dict, sa_column=Column(JSON),
                                 description="工具类别的schema内容，符合openapi规范的json")


class GptsToolsTypeRead(GptsToolsTypeBase):
    children: Optional[List[GptsTools]] = Field(default=[], description="工具类别下的工具列表")


class GptsToolsRead(GptsToolsBase):
    id: int


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
    def get_list_by_user(cls, user_id: int) -> List[GptsToolsRead]:
        with session_getter() as session:
            statement = select(GptsTools).where(
                or_(GptsTools.user_id == user_id,
                    GptsTools.is_preset == 1)).where(GptsTools.is_delete == 0)
            list_tools = session.exec(statement).all()
            return [GptsToolsRead.validate(item) for item in list_tools]

    @classmethod
    def get_list_by_type(cls, tool_type_ids: List[int]) -> List[GptsTools]:
        """
        获得工具类别下的所有的工具
        """
        with session_getter() as session:
            statement = select(GptsTools).where(
                GptsTools.type.in_(tool_type_ids)).where(
                GptsTools.is_delete == 0).order_by(GptsTools.create_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_tool_type(cls, user_id: int) -> List[GptsToolsType]:
        """
        获得所有的工具类别，包含预置和用户自己的
        """
        with session_getter() as session:
            statement = select(GptsToolsType).where(GptsToolsType.is_delete == 0).where(
                or_(GptsToolsType.user_id == user_id, GptsToolsType.is_preset == 1)
            ).order_by(GptsToolsType.id.desc())
            return session.exec(statement).all()

    @classmethod
    def get_one_tool_type(cls, tool_type_id: int) -> GptsToolsType:
        """
        获取某个类别的详情，包含openapi的schema协议内容
        """
        with session_getter() as session:
            statement = select(GptsToolsType).where(GptsToolsType.id == tool_type_id)
            return session.exec(statement).first()

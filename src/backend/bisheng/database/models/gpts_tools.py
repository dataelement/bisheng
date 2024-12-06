from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import JSON, Column, DateTime, String, text, func
from sqlmodel import Field, or_, select, Text, update


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
    extra: Optional[str] = Field(default='', sa_column=Column(String(length=2048)),
                                 description="工具类别的配置信息，用来存储工具类别所需的配置信息")
    description: str = Field(default='', description="工具类别的描述")
    server_host: Optional[str] = Field(default='', description="自定义工具的访问根地址，必须以http或者https开头")
    auth_method: Optional[int] = Field(default=0, description="工具类别的鉴权方式")
    api_key: Optional[str] = Field(default='', description="工具鉴权的api_key")
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description="工具鉴权的鉴权方式")
    is_preset: Optional[int] = Field(default=0, description="是否是预置工具类别")
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
    openapi_schema: str = Field(default="", sa_column=Column(Text),
                                description="工具类别的schema内容，符合openapi规范的数据")


class GptsToolsTypeRead(GptsToolsTypeBase):
    openapi_schema: Optional[str] = Field(default="", description="工具类别的schema内容，符合openapi规范的数据")
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
    def get_list_by_user(cls, user_id: int, page: int = 0, page_size: int = 0) -> List[GptsTools]:
        """
        获得用户可用的所有工具
        """
        with session_getter() as session:
            statement = select(GptsTools).where(
                or_(GptsTools.user_id == user_id,
                    GptsTools.is_preset == 1)).where(GptsTools.is_delete == 0)
            if page and page_size:
                statement = statement.offset((page - 1) * page_size).limit(page_size)
            statement = statement.order_by(GptsTools.create_time.desc())
            list_tools = session.exec(statement).all()
            return list_tools

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
    def get_all_tool_type(cls, tool_type_ids: List[int]) -> List[GptsToolsType]:
        """
        获得所有的工具类别
        """
        with session_getter() as session:
            statement = select(GptsToolsType).filter(
                GptsToolsType.is_delete == 0,
                GptsToolsType.id.in_(tool_type_ids)
            )
            return session.exec(statement).all()

    @classmethod
    def get_preset_tool_type(cls) -> List[GptsToolsType]:
        """
        获得所有的预置工具类别
        """
        with session_getter() as session:
            statement = select(GptsToolsType).where(GptsToolsType.is_preset == 1, GptsToolsType.is_delete == 0)
            return session.exec(statement).all()

    @classmethod
    def get_user_tool_type(cls, user_id: int, extra_tool_type_ids: List[int], include_preset: bool = True) \
            -> List[GptsToolsType]:
        """
        获取用户可见的所有工具类别
        """
        statement = select(GptsToolsType).where(GptsToolsType.is_delete == 0)
        filters = []
        if extra_tool_type_ids:
            filters.append(or_(
                GptsToolsType.id.in_(extra_tool_type_ids),
                GptsToolsType.user_id == user_id
            ))
        else:
            filters.append(GptsToolsType.user_id == user_id)
        if include_preset:
            filters.append(GptsToolsType.is_preset == 1)
        statement = statement.where(or_(*filters))
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def filter_tool_types_by_ids(cls, tool_type_ids: List[int], keyword: Optional[str] = None, page: int = 0,
                                 limit: int = 0, include_preset: bool = False) -> (List[GptsToolsType], int):
        """
        根据工具类别id过滤工具类别
        """
        statement = select(GptsToolsType).where(GptsToolsType.is_delete == 0)
        count_statement = select(func.count(GptsToolsType.id)).where(GptsToolsType.is_delete == 0)
        if not include_preset:
            statement = statement.where(GptsToolsType.is_preset == 0)
            count_statement = count_statement.where(GptsToolsType.is_preset == 0)

        if tool_type_ids:
            statement = statement.where(GptsToolsType.id.in_(tool_type_ids))
            count_statement = count_statement.where(GptsToolsType.id.in_(tool_type_ids))
        if keyword:
            statement = statement.where(or_(
                GptsToolsType.name.like(f'%{keyword}%'),
                GptsToolsType.description.like(f'%{keyword}%')
            ))
            count_statement = count_statement.where(or_(
                GptsToolsType.name.like(f'%{keyword}%'),
                GptsToolsType.description.like(f'%{keyword}%')
            ))

        if limit and page:
            statement = statement.offset(
                (page - 1) * limit
            ).limit(limit).order_by(GptsToolsType.update_time.desc())
        with session_getter() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def get_one_tool_type(cls, tool_type_id: int) -> GptsToolsType:
        """
        获取某个类别的详情，包含openapi的schema协议内容
        """
        with session_getter() as session:
            statement = select(GptsToolsType).where(GptsToolsType.id == tool_type_id)
            return session.exec(statement).first()

    @classmethod
    def get_one_tool_type_by_name(cls, user_id: int, tool_type_name: str) -> GptsToolsType:
        """
        获取某个工具类别的详细信息
        """
        with session_getter() as session:
            statement = select(GptsToolsType).filter(
                GptsToolsType.name == tool_type_name,
                GptsToolsType.user_id == user_id,
                GptsToolsType.is_delete == 0
            )
            return session.exec(statement).first()

    @classmethod
    def insert_tool_type(cls, data: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """
        新增工具类别 和对应的工具列表
        """
        children = data.children
        gpts_tool_type = GptsToolsType(**data.model_dump(exclude={'children'}))
        # 插入工具类别
        with session_getter() as session:
            session.add(gpts_tool_type)
            session.commit()
            session.refresh(gpts_tool_type)
        with session_getter() as session:
            # 插入工具列表
            for one in children:
                one.type = gpts_tool_type.id
                one.tool_key = cls.get_tool_key(gpts_tool_type.id, one.tool_key)
            session.add_all(children)
            session.commit()
        res = GptsToolsTypeRead(**gpts_tool_type.model_dump(), children=children)
        return res

    @classmethod
    def update_tool_type(cls, data: GptsToolsType,
                         del_tool_ids: List[int],
                         add_tool_list: List[GptsTools],
                         update_tool_list: List[GptsTools]):
        """
        更新工具类别的信息
        param data: GptsToolsType
        param del_tool_ids: 需要删除的工具id
        param add_tool_list: 需要新增的工具列表
        param update_tool_list: 需要更新的工具列表
        """
        finally_children = []
        with session_getter() as session:
            # 更新工具类别的数据
            session.add(data)
            # 删除不存在的工具列表
            session.exec(update(GptsTools).where(
                GptsTools.id.in_(del_tool_ids)
            ).values(is_delete=1))
            # 新增工具列表
            for one in add_tool_list:
                one.type = data.id
                one.tool_key = cls.get_tool_key(data.id, one.tool_key)
                session.add(one)
                finally_children.append(one)
            # 更新工具列表
            for one in update_tool_list:
                session.add(one)
                finally_children.append(one)
            session.commit()
            session.refresh(data)

    @classmethod
    def delete_tool_type(cls, tool_type_id: int) -> None:
        """
        删除工具类别
        """
        with session_getter() as session:
            session.exec(
                update(GptsToolsType).filter(
                    GptsToolsType.id == tool_type_id,
                    GptsToolsType.is_preset == 0,
                ).values(is_delete=1)
            )
            session.exec(
                update(GptsTools).filter(
                    GptsTools.type == tool_type_id,
                    GptsToolsType.is_preset == False
                ).values(is_delete=1)
            )
            session.commit()

    @classmethod
    def get_tool_key(cls, tool_type_id: int, tool_key: str) -> str:
        """
        拼接自定义工具的tool_key
        """
        return f"tool_type_{tool_type_id}_{tool_key}"

    @classmethod
    def update_tools_extra(cls, tool_type_id: int, extra: str) -> bool:
        with session_getter() as session:
            statement = update(GptsToolsType).where(GptsToolsType.id == tool_type_id).values(extra=extra)
            session.exec(statement)
            statement = update(GptsTools).where(GptsTools.type == tool_type_id).values(extra=extra)
            session.exec(statement)
            session.commit()
            return True

    @classmethod
    def get_tool_by_tool_key(cls, tool_key: str) -> GptsTools:
        with session_getter() as session:
            statement = select(GptsTools).where(GptsTools.tool_key == tool_key)
            return session.exec(statement).first()

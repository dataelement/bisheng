import json
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import model_validator
from sqlalchemy import JSON, Column, DateTime, String, text, func
from sqlmodel import Field, or_, select, Text, update, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.utils import md5_hash, generate_uuid
from bisheng.utils.mask_data import JsonFieldMasker
from ..const import AuthType, ToolPresetType


class GptsToolsBase(SQLModelSerializable):
    name: str = Field(sa_column=Column(String(length=125), index=True))
    logo: Optional[str] = Field(default=None, sa_column=Column(String(length=512), index=False))
    desc: Optional[str] = Field(default=None, sa_column=Column(String(length=2048), index=False))
    tool_key: str = Field(sa_column=Column(String(length=125), index=False))
    type: int = Field(default=0, description='of the category to which they belongID')
    is_preset: int = Field(default=ToolPresetType.API.value, description="The category of the tool, the historical reason field is not renamed")
    is_delete: int = Field(default=0, description='1 Indicates logical deletion')
    api_params: Optional[List[Dict]] = Field(default=None, sa_column=Column(JSON), description='Used to storeapiParameter and other information')
    user_id: Optional[int] = Field(default=None, index=True, description='Create UserID， nullIndicates system creation')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class GptsToolsTypeBase(SQLModelSerializable):
    id: Optional[int] = Field(default=None, index=True, primary_key=True)
    name: str = Field(default='', sa_column=Column(String(length=1024)), description="Tool Category Name")
    logo: Optional[str] = Field(default='', description="of the tool categorylogoFile URL")
    extra: Optional[str] = Field(default='{}', sa_column=Column(Text),
                                 description="Configuration information for the tool category to store the configuration information required for the tool category")
    description: str = Field(default='', description="Description of the tool category")
    server_host: Optional[str] = Field(default='', description="The access root address of the custom tool, which must behttporhttpsWhat/the beginning?")
    auth_method: Optional[int] = Field(default=0, description="Authentication method of tool category")
    api_key: Optional[str] = Field(default='', description="Tool Authenticationapi_key", sa_column=Column(String(length=2048)),
                                   max_length=1000)
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description="Authentication method of tool authentication")
    is_preset: Optional[int] = Field(default=ToolPresetType.API.value, description="The category of the tool, the historical reason field is not renamed")
    user_id: Optional[int] = Field(default=None, index=True, description='Create UserID， nullIndicates system creation')
    is_delete: int = Field(default=0, description='1 Indicates logical deletion')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class GptsTools(GptsToolsBase, table=True):
    __tablename__ = 't_gpts_tools'
    extra: Optional[str | dict] = Field(default=None, sa_column=Column(Text, index=False),
                                        description='Used to store additional information, such as parameter requirements, including &initdb_conf_key Data field'
                                                    'Indicates that the configuration information is obtained from the system configuration,For multi-level use.with ')
    id: Optional[int] = Field(default=None, primary_key=True)


class GptsToolsType(GptsToolsTypeBase, table=True):
    __tablename__ = 't_gpts_tools_type'
    openapi_schema: str = Field(default="", sa_column=Column(Text),
                                description="of the tool categoryschemaContent, complies withopenapiSpecified Data")


class GptsToolsTypeRead(GptsToolsTypeBase):
    openapi_schema: Optional[str] = Field(default="", description="of the tool categoryschemaContent, complies withopenapiSpecified Data")
    children: Optional[List[GptsTools]] = Field(default_factory=list, description="List of tools under the Tools category")
    parameter_name: Optional[str] = Field(default="", description="Custom request header parameter name")
    api_location: Optional[str] = Field(default="", description="Custom Request Header Parameter Position header or query")
    write: Optional[bool] = Field(default=False, description="Do you have write access")

    @model_validator(mode="after")
    def validate(self):
        # Needs to be populated when echoingapi_locationAndparameter_nameData field
        if self.extra and not self.api_location:
            result = json.loads(self.extra)
            self.api_location = result.get('api_location')
            self.parameter_name = result.get('parameter_name')

    def mask_sensitive_data(self):
        json_masker = JsonFieldMasker()
        # The provisioning tool needs to be desensitizedextraData field
        if self.extra and self.is_preset == ToolPresetType.PRESET.value:
            extra_json = json.loads(self.extra)
            extra_json = json_masker.mask_json(extra_json)
            self.extra = json.dumps(extra_json, ensure_ascii=False)
        return self


class GptsToolsRead(GptsToolsBase):
    id: int


class GptsToolsDao(GptsToolsBase):

    @classmethod
    def insert(cls, obj: GptsTools):
        with get_sync_db_session() as session:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    @classmethod
    def query_by_name(cls, name: str) -> List[GptsTools]:
        with get_sync_db_session() as session:
            statement = select(GptsTools).where(GptsTools.name.like(f'%{name}%'))
            return session.exec(statement).all()

    @classmethod
    def update_tools(cls, data: GptsTools) -> GptsTools:
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def update_tool_list(cls, data: List[GptsTools]) -> List[GptsTools]:
        with get_sync_db_session() as session:
            for one in data:
                session.add(one)
            session.commit()
            return data

    @classmethod
    def delete_tool(cls, data: GptsTools) -> GptsTools:
        data.is_delete = 1
        return cls.update_tools(data)

    @classmethod
    def delete_tool_by_ids(cls, tool_ids: List[int]) -> None:
        with get_sync_db_session() as session:
            statement = update(GptsTools).where(GptsTools.id.in_(tool_ids)).values(is_delete=1)
            session.exec(statement)
            session.commit()

    @classmethod
    def get_one_tool(cls, tool_id: int) -> GptsTools:
        with get_sync_db_session() as session:
            statement = select(GptsTools).where(GptsTools.id == tool_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_one_tool(cls, tool_id: int) -> GptsTools:
        statement = select(GptsTools).where(GptsTools.id == tool_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_list_by_ids(cls, tool_ids: List[int]) -> List[GptsTools]:
        statement = select(GptsTools).where(col(GptsTools.id).in_(tool_ids)).where(GptsTools.is_delete == 0)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_list_by_ids(cls, tool_ids: List[int]) -> List[GptsTools]:
        statement = select(GptsTools).where(col(GptsTools.id).in_(tool_ids)).where(GptsTools.is_delete == 0)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_list_by_user(cls, user_id: int, page: int = 0, page_size: int = 0) -> List[GptsTools]:
        """
        Get all the tools available to your users
        """
        with get_sync_db_session() as session:
            statement = select(GptsTools).where(
                or_(GptsTools.user_id == user_id,
                    GptsTools.is_preset == ToolPresetType.PRESET.value)).where(GptsTools.is_delete == 0)
            if page and page_size:
                statement = statement.offset((page - 1) * page_size).limit(page_size)
            statement = statement.order_by(GptsTools.create_time.desc())
            list_tools = session.exec(statement).all()
            return list_tools

    @classmethod
    def get_list_by_type(cls, tool_type_ids: List[int]) -> List[GptsTools]:
        """
        Get all the tools under the Tools category
        """
        with get_sync_db_session() as session:
            statement = select(GptsTools).where(
                GptsTools.type.in_(tool_type_ids)).where(
                GptsTools.is_delete == 0).order_by(GptsTools.create_time.desc())
            return session.exec(statement).all()

    @classmethod
    async def aget_list_by_type(cls, tool_type_ids: List[int]) -> List[GptsTools]:
        """
        Get all the tools under the Tools category asynchronously
        """
        statement = select(GptsTools).where(
            GptsTools.type.in_(tool_type_ids)).where(
            GptsTools.is_delete == 0).order_by(GptsTools.create_time.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_all_tool_type(cls, tool_type_ids: List[int]) -> List[GptsToolsType]:
        """
        Get all tool categories
        """
        with get_sync_db_session() as session:
            statement = select(GptsToolsType).filter(
                GptsToolsType.is_delete == 0,
                GptsToolsType.id.in_(tool_type_ids)
            )
            return session.exec(statement).all()

    @classmethod
    async def aget_all_tool_type(cls, tool_type_ids: List[int]) -> List[GptsToolsType]:
        """ get tool types by tool ids """
        statement = select(GptsToolsType).filter(
            col(GptsToolsType.is_delete) == 0,
            col(GptsToolsType.id).in_(tool_type_ids)
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_preset_tool_type(cls) -> List[GptsToolsType]:
        """
        Get all preset tool categories
        """
        with get_sync_db_session() as session:
            statement = select(GptsToolsType).where(GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                                                    GptsToolsType.is_delete == 0)
            statement = statement.order_by(GptsToolsType.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    async def aget_preset_tool_type(cls) -> List[GptsToolsType]:
        """
        Get all preset tool categories asynchronously
        """
        statement = select(GptsToolsType).where(GptsToolsType.is_preset == ToolPresetType.PRESET.value,
                                                GptsToolsType.is_delete == 0)
        statement = statement.order_by(GptsToolsType.update_time.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def _get_user_tool_type_statement(cls, user_id: int, extra_tool_type_ids: List[int] = None,
                                      include_preset: bool = True,
                                      is_preset: ToolPresetType = None):
        """
        Get the value of all tool categories visible to the userstatement
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
            filters.append(GptsToolsType.is_preset == ToolPresetType.PRESET.value)
        if is_preset is not None:
            statement = statement.where(GptsToolsType.is_preset == is_preset.value)
        statement = statement.where(or_(*filters))
        statement = statement.order_by(func.field(GptsToolsType.is_preset,
                                                  ToolPresetType.PRESET.value).desc(),
                                       GptsToolsType.update_time.desc())
        return statement

    @classmethod
    def get_user_tool_type(cls, user_id: int, extra_tool_type_ids: List[int] = None, include_preset: bool = True,
                           is_preset: ToolPresetType = None) -> List[GptsToolsType]:
        """
        Get all tool categories visible to the user
        """
        statement = cls._get_user_tool_type_statement(user_id, extra_tool_type_ids, include_preset, is_preset)
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    async def aget_user_tool_type(cls, user_id: int, extra_tool_type_ids: List[int] = None, include_preset: bool = True,
                                  is_preset: ToolPresetType = None) -> List[GptsToolsType]:
        """
        Get all tool categories visible to the user
        """
        statement = cls._get_user_tool_type_statement(user_id, extra_tool_type_ids, include_preset, is_preset)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def filter_tool_types_by_ids(cls, tool_type_ids: List[int], keyword: Optional[str] = None, page: int = 0,
                                 limit: int = 0, include_preset: bool = False) -> (List[GptsToolsType], int):
        """
        By Tool CategoryidFilter Category
        """
        statement = select(GptsToolsType).where(GptsToolsType.is_delete == 0)
        count_statement = select(func.count(GptsToolsType.id)).where(GptsToolsType.is_delete == 0)
        if not include_preset:
            statement = statement.where(GptsToolsType.is_preset != ToolPresetType.PRESET.value)
            count_statement = count_statement.where(GptsToolsType.is_preset != ToolPresetType.PRESET.value)

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
        with get_sync_db_session() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def get_one_tool_type(cls, tool_type_id: int) -> GptsToolsType:
        """
        Get details about a category, includingopenapiright of privacyschemaAgreement Wording
        """
        with get_sync_db_session() as session:
            statement = select(GptsToolsType).where(GptsToolsType.id == tool_type_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_one_tool_type(cls, tool_type_id: int) -> GptsToolsType:
        """
        Get details about a category asynchronously, includingopenapiright of privacyschemaAgreement Wording
        """
        statement = select(GptsToolsType).where(GptsToolsType.id == tool_type_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def get_one_tool_type_by_name(cls, user_id: int, tool_type_name: str) -> GptsToolsType:
        """
        Get the details of a tool category asynchronously
        """
        statement = select(GptsToolsType).filter(
            col(GptsToolsType.name) == tool_type_name,
            col(GptsToolsType.user_id) == user_id,
            col(GptsToolsType.is_delete) == 0
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def insert_tool_type(cls, data: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """
        Add Tool Category and the corresponding list of tools
        """
        children = data.children
        gpts_tool_type = GptsToolsType(**data.model_dump(exclude={'children'}))
        # Insert Tool Category
        async with get_async_db_session() as session:
            session.add(gpts_tool_type)
            await session.commit()
            await session.refresh(gpts_tool_type)
            if children:
                # Insert Tools List
                for one in children:
                    one.type = gpts_tool_type.id
                    one.tool_key = cls.get_tool_key(gpts_tool_type.id, one)
                session.add_all(children)
                await session.commit()
        res = GptsToolsTypeRead(**gpts_tool_type.model_dump(), children=children)
        return res

    @classmethod
    async def update_tool_type(cls, data: GptsToolsType,
                               del_tool_ids: List[int],
                               add_tool_list: List[GptsTools],
                               update_tool_list: List[GptsTools]):
        """
        Update Tool Category Information
        param data: GptsToolsType
        param del_tool_ids: Tools to removeid
        param add_tool_list: List of tools that need to be added
        param update_tool_list: List of tools that need to be updated
        """
        finally_children = []
        async with get_async_db_session() as session:
            # Update tool category data
            session.add(data)
            # Delete a list of tools that don't exist
            delete_old_tools = update(GptsTools).where(GptsTools.id.in_(del_tool_ids)).values(is_delete=1)
            await session.exec(delete_old_tools)
            # Add Tool List
            for one in add_tool_list:
                one.type = data.id
                one.tool_key = cls.get_tool_key(data.id, one)
                session.add(one)
                finally_children.append(one)
            # Update Tool List
            for one in update_tool_list:
                session.add(one)
                finally_children.append(one)
            await session.commit()
            await session.refresh(data)

    @classmethod
    async def delete_tool_type(cls, tool_type_id: int) -> None:
        """
        Delete Tool Category
        """
        statement = update(GptsToolsType).where(col(GptsToolsType.id) == tool_type_id,
                                                col(GptsToolsType.is_preset) != ToolPresetType.PRESET.value).values(
            is_delete=1)
        tool_statement = update(GptsTools).where(col(GptsTools.type) == tool_type_id,
                                                 col(GptsTools.is_preset) != ToolPresetType.PRESET.value).values(
            is_delete=1)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.exec(tool_statement)
            await session.commit()

    @classmethod
    def get_tool_key(cls, tool_type_id: int, gpt_tool: GptsTools) -> str:
        """
        of stitching custom toolstool_key
        """
        if gpt_tool.is_preset == ToolPresetType.MCP.value:
            return f"{gpt_tool.name}_{generate_uuid()[:8]}"
        return f"tool_type_{tool_type_id}_{md5_hash(gpt_tool.name)}"

    @classmethod
    async def update_tools_extra(cls, tool_type_id: int, extra: str) -> bool:
        async with get_async_db_session() as session:
            statement = update(GptsToolsType).where(col(GptsToolsType.id) == tool_type_id).values(extra=extra)
            await session.exec(statement)
            statement = update(GptsTools).where(col(GptsTools.type) == tool_type_id).values(extra=text('NULL'))
            await session.exec(statement)
            await session.commit()
            return True

    @classmethod
    def get_tool_by_tool_key(cls, tool_key: str) -> GptsTools:
        with get_sync_db_session() as session:
            statement = select(GptsTools).where(GptsTools.tool_key == tool_key)
            return session.exec(statement).first()

    @classmethod
    async def aget_tool_by_tool_key(cls, tool_key: str) -> GptsTools:
        statement = select(GptsTools).where(GptsTools.tool_key == tool_key)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

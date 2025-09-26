import json
from typing import Optional, List

import yaml
from fastapi import Request
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, ConfigDict

from bisheng.api.errcode.assistant import ToolTypeNotExistsError, ToolTypeRepeatError
from bisheng.api.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.api.services.openapi import OpenApiSchema
from bisheng.api.services.tool.langchain_tool.search_knowledge import SearchKnowledgeBase
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_url_content
from bisheng.database.constants import ToolPresetType
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsTools, GptsToolsType, GptsToolsTypeRead
from bisheng.database.models.role_access import AccessType
from bisheng.mcp_manage.manager import ClientManager
from bisheng.utils import md5_hash
from bisheng_langchain.gpts.load_tools import load_tools


class ToolServices(BaseModel):
    """ 工具服务类 """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Optional[Request] = None
    login_user: Optional[UserPayload] = None

    async def get_manage_tools(self, is_preset: Optional[ToolPresetType] = None) -> List[GptsToolsTypeRead]:
        """ 获取有管理权限的工具列表 """
        tool_type_ids_extra = []
        if is_preset != ToolPresetType.PRESET:
            tool_type_ids_extra = self.login_user.get_user_access_resource_ids([AccessType.GPTS_TOOL_WRITE])

        if is_preset is None:
            # 获取所有的工具列表
            all_tool_type = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, tool_type_ids_extra)
        elif is_preset == ToolPresetType.PRESET:
            # 获取预置工具列表
            all_tool_type = await GptsToolsDao.aget_preset_tool_type()
        else:
            # 获取用户有管理权限的工具列表
            all_tool_type = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, tool_type_ids_extra, False,
                                                                   is_preset)

        if not all_tool_type:
            return []
        tool_type_id = []
        res = []
        tool_type_children = {}
        for one in all_tool_type:
            tool_type_id.append(one.id)
            tool_type_children[one.id] = []
            res.append(one.model_dump())
        tool_type_id = list(set(tool_type_id))
        # find all tools by type id
        tool_list = await GptsToolsDao.aget_list_by_type(tool_type_id)
        for one in tool_list:
            if one.is_preset == ToolPresetType.PRESET.value:
                one.extra = None
            tool_type_children[one.type].append(one.model_dump())

        # 组装children
        for one in res:
            # 预置工具的配置只有管理员可以查看
            if one["is_preset"] == ToolPresetType.PRESET.value and not self.login_user.is_admin():
                one["extra"] = None
            one["children"] = tool_type_children.get(one["id"], [])
            if one['extra']:
                extra = json.loads(one['extra'])
                one["parameter_name"] = extra.get("parameter_name")
                one["api_location"] = extra.get("api_location")
        return res

    async def parse_openapi_schema(self, download_url: str, file_content: str) -> GptsToolsTypeRead:
        if download_url:
            try:
                file_content = await get_url_content(download_url)
            except Exception as e:
                logger.exception(f'file {download_url} download error')
                raise ServerError.http_exception(msg='url文件下载失败：' + str(e))
        if not file_content:
            raise ServerError.http_exception(msg='schema内容不能为空')
        # 根据文件内容是否以`{`开头判断用什么解析方式
        try:
            if file_content.startswith('{'):
                res = json.loads(file_content)
            else:
                res = yaml.safe_load(file_content)
        except Exception as e:
            logger.exception(f'openapi schema parse error {e}')
            raise ServerError.http_exception(msg=f'openapi schema解析报错，请检查内容是否符合json或者yaml格式: {str(e)}')

        #  解析openapi schema转为助手工具的格式
        try:
            schema = OpenApiSchema(res)
            schema.parse_server()
            if not schema.default_server.startswith(('http', 'https')):
                raise ServerError.http_exception(msg=f'server中的url必须以http或者https开头: {schema.default_server}')
            tool_type = GptsToolsTypeRead(name=schema.title,
                                          description=schema.description,
                                          is_preset=ToolPresetType.API.value,
                                          server_host=schema.default_server,
                                          openapi_schema=file_content,
                                          api_location=schema.api_location,
                                          parameter_name=schema.parameter_name,
                                          auth_type=schema.auth_type,
                                          auth_method=schema.auth_method,
                                          children=[])
            # 解析获取所有的api
            schema.parse_paths()
            for one in schema.apis:
                tool_type.children.append(
                    GptsTools(
                        name=one['operationId'],
                        desc=one['description'],
                        tool_key=md5_hash(one['operationId']),
                        is_preset=0,
                        is_delete=0,
                        api_params=one['parameters'],
                        extra=json.dumps(one, ensure_ascii=False),
                    ))
            return tool_type
        except Exception as e:
            logger.exception(f'openapi schema parse error {e}')
            raise ServerError.http_exception(msg='openapi schema解析失败：' + str(e))

    async def parse_mcp_schema(self, file_content: str) -> GptsToolsTypeRead:
        try:
            result = json.loads(file_content)
            mcp_servers = result['mcpServers']
        except Exception as e:
            logger.exception(f'mcp tool schema parse error {e}')
            raise ServerError.http_exception(msg=f'mcp工具配置解析失败，请检查内容是否符合mcp配置格式: {str(e)}')
        tool_type = None
        for key, value in mcp_servers.items():
            # 解析mcp服务配置
            tool_type = GptsToolsTypeRead(name=value.get('name', ''),
                                          server_host=value.get('url', ''),
                                          description=value.get('description', ''),
                                          is_preset=ToolPresetType.MCP.value,
                                          openapi_schema=file_content,
                                          children=[])
            # 实例化mcp服务对象，获取工具列表
            client = await ClientManager.connect_mcp_from_json(result)

            tools = await client.list_tools()

            for one in tools:
                tool_type.children.append(GptsTools(
                    name=one.name,
                    desc=one.description,
                    tool_key=md5_hash(one.name),
                    is_preset=ToolPresetType.MCP.value,
                    api_params=ToolServices.convert_input_schema(one.inputSchema),
                    extra=one.model_dump_json(),
                ))
            break
        if tool_type is None:
            raise ServerError.http_exception(msg='mcp服务配置解析失败，请检查配置里是否配置了mcpServers')
        return tool_type

    @classmethod
    async def _update_gpts_tools(cls, exist_tool_type: GptsToolsType, req: GptsToolsTypeRead) -> GptsToolsTypeRead:
        exist_tool_type.name = req.name
        exist_tool_type.logo = req.logo
        exist_tool_type.description = req.description
        exist_tool_type.server_host = req.server_host
        exist_tool_type.auth_method = req.auth_method
        exist_tool_type.api_key = req.api_key
        exist_tool_type.auth_type = req.auth_type
        exist_tool_type.openapi_schema = req.openapi_schema
        tool_extra = {"api_location": req.api_location, "parameter_name": req.parameter_name}
        exist_tool_type.extra = json.dumps(tool_extra, ensure_ascii=False)

        children_map = {}
        for one in req.children:
            children_map[one.name] = one

        # 获取此类别下旧的API列表
        old_tool_list = GptsToolsDao.get_list_by_type([exist_tool_type.id])
        # 需要被删除的工具列表
        delete_tool_id_list = []
        # 需要被更新的工具列表
        update_tool_list = []
        for one in old_tool_list:
            # 说明此工具 需要删除
            if children_map.get(one.name) is None:
                delete_tool_id_list.append(one.id)
            else:
                # 说明此工具需要更新
                new_tool_info = children_map.pop(one.name)
                one.name = new_tool_info.name
                one.desc = new_tool_info.desc
                one.extra = new_tool_info.extra
                one.api_params = new_tool_info.api_params
                update_tool_list.append(one)

        add_children = []
        for one in children_map.values():
            one.id = None
            one.user_id = exist_tool_type.user_id
            one.is_preset = exist_tool_type.is_preset
            one.is_delete = 0
            add_children.append(one)

        GptsToolsDao.update_tool_type(exist_tool_type, delete_tool_id_list,
                                      add_children, update_tool_list)

        children = GptsToolsDao.get_list_by_type([exist_tool_type.id])
        return GptsToolsTypeRead(**exist_tool_type.model_dump(), children=children)

    @classmethod
    async def update_gpts_tools(cls, user: UserPayload, req: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """
        更新工具类别，包括更新工具类别的名称和删除、新增工具类别的API
        """
        # 尝试解析下openapi schema看下是否可以正常解析, 不能的话保存不允许保存
        tool_service = ToolServices()
        if req.is_preset == ToolPresetType.API.value:
            await tool_service.parse_openapi_schema('', req.openapi_schema)
        elif req.is_preset == ToolPresetType.MCP.value:
            await tool_service.parse_mcp_schema(req.openapi_schema)

        exist_tool_type = GptsToolsDao.get_one_tool_type(req.id)
        if not exist_tool_type:
            raise ToolTypeNotExistsError.http_exception()
        if req.name.__len__() > 1000 or req.name.__len__() == 0:
            raise ServerError.http_exception(msg="名字不符合规范：至少1个字符，不能超过1000个字符")

        #  判断工具类别名称是否重复
        tool_type = GptsToolsDao.get_one_tool_type_by_name(user.user_id, req.name)
        if tool_type and tool_type.id != exist_tool_type.id:
            raise ToolTypeRepeatError.http_exception()
        # 判断是否有更新权限
        if not user.access_check(exist_tool_type.user_id, str(exist_tool_type.id), AccessType.GPTS_TOOL_WRITE):
            raise UnAuthorizedError.http_exception()

        return await cls._update_gpts_tools(exist_tool_type, req)

    async def refresh_all_mcp(self) -> str:
        """ return mcp server error msg """
        # get user all mcp tool
        tool_types = GptsToolsDao.get_user_tool_type(self.login_user.user_id, is_preset=ToolPresetType.MCP)
        if not tool_types:
            return ''

        tools = GptsToolsDao.get_list_by_type(tool_type_ids=[one.id for one in tool_types])
        tools_map = {}
        for one in tools:
            if one.type not in tools_map:
                tools_map[one.type] = []
            tools_map[one.type].append(one)
        error_msg = ''
        for one in tool_types:
            try:
                await self.refresh_mcp_tools(one, tools_map.get(one.id, []))
            except Exception as e:
                logger.exception(f'{one.name}刷新工具失败:')
                error_msg += f'{one.name}工具获取失败，请重试\n'
        return error_msg

    async def refresh_mcp_tools(self, tool_type: GptsToolsType, old_tools: list[GptsTools]):
        """ refresh mcp tools """
        # 1. get all new tools
        # 实例化mcp服务对象，获取工具列表
        client = await ClientManager.connect_mcp_from_json(tool_type.openapi_schema)
        tools = await client.list_tools()
        children = []
        for one in tools:
            children.append(GptsTools(
                name=one.name,
                desc=one.description,
                is_preset=ToolPresetType.MCP.value,
                api_params=self.convert_input_schema(one.inputSchema),
                extra=one.model_dump_json(),
                type=tool_type.id,
            ))

        req = GptsToolsTypeRead(**tool_type.model_dump(), children=children)
        await self._update_gpts_tools(tool_type, req)

    @classmethod
    def convert_input_schema(cls, input_schema: dict):
        """ 转换mcp工具的输入参数 为自定义工具的格式"""
        required = input_schema.get('required', [])
        properties = input_schema.get('properties', {})
        res = []
        for filed, field_info in properties.items():
            res.append({
                'in': "query",
                'name': filed,
                'description': field_info.get('description'),
                'required': filed in required,
                'schema': {
                    'type': field_info.get('type'),
                }
            })
        return res

    @classmethod
    async def init_linsight_tools(cls, root_path: str) -> List[BaseTool]:
        """ 初始化Linsight 默认的工具, 特殊点在于本地文件工具初始化的参数不是固定的，而是再运行期间确定的 """
        # 加载本地文件操作相关工具
        local_file_tools = load_tools({
            "list_files": {"root_path": root_path},
            "get_file_details": {"root_path": root_path},
            "search_files": {"root_path": root_path},
            # "search_text_in_file": {"root_path": root_path},
            "read_text_file": {"root_path": root_path},
            "add_text_to_file": {"root_path": root_path},
            "replace_file_lines": {"root_path": root_path},
        })
        knowledge_tools = [SearchKnowledgeBase()]
        return knowledge_tools + local_file_tools

    @classmethod
    async def get_linsight_tools(cls) -> list[GptsToolsTypeRead]:
        return [
            GptsToolsTypeRead(
                id=100000,
                name="知识库和文件内容检索",
                description="检索组织知识库、个人知识库以及本地上传文件的内容",
                children=[
                    GptsTools(
                        id=100001,
                        name="知识库和文件内容检索",
                        desc="检索组织知识库、个人知识库以及本地上传文件的内容。",
                        tool_key="search_knowledge_base",
                    )
                ]
            ),
            GptsToolsTypeRead(
                id=200000,
                name="文件操作",
                description="本地文件系统的浏览、搜索与编辑工具集",
                children=[
                    GptsTools(
                        id=200001,
                        name="获取所有文件和目录",
                        desc="列出指定目录下的所有文件和子目录。",
                        tool_key="list_files"
                    ),
                    GptsTools(
                        id=200002,
                        name="获取文件详细信息",
                        desc="获取指定文件的文件名、文件大小、文件地址、字数、行数等详细信息。",
                        tool_key="get_file_details"
                    ),
                    GptsTools(
                        id=200003,
                        name="搜索文件",
                        desc="在指定目录中搜索文件和子目录。",
                        tool_key="search_files"
                    ),
                    GptsTools(
                        id=200004,
                        name="读取文件内容",
                        desc="读取本地文本文件的内容。",
                        tool_key="read_text_file"
                    ),
                    GptsTools(
                        id=200005,
                        name="写入文件内容",
                        desc="将文本内容追加到文本文件，如果文件不存在，则创建文件",
                        tool_key="add_text_to_file"
                    ),
                    GptsTools(
                        id=200006,
                        name="替换文件指定行范围内容",
                        desc="替换文件中的指定行范围。",
                        tool_key="replace_file_lines"
                    ),
                ]
            )
        ]

from fastapi import Request
from loguru import logger
from pydantic import BaseModel, ConfigDict

from bisheng.api.services.user_service import UserPayload
from bisheng.database.constants import ToolPresetType
from bisheng.database.models.gpts_tools import GptsToolsDao, GptsTools, GptsToolsType
from bisheng.mcp_manage.constant import McpClientType
from bisheng.mcp_manage.manager import ClientManager
from bisheng.utils import md5_hash


class ToolServices(BaseModel):
    """ 工具服务类 """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Request
    login_user: UserPayload

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
                error_msg += f'{one.name}工具获取失败，请重试'
        return error_msg

    async def refresh_mcp_tools(self, tool_type: GptsToolsType, old_tools: list[GptsTools]):
        """ refresh mcp tools """
        # 1. get all new tools
        # 实例化mcp服务对象，获取工具列表
        client = await ClientManager.connect_mcp_from_json(tool_type.openapi_schema)
        tools = await client.list_tools()
        new_tools = {}
        for one in tools:
            tool_key = GptsToolsDao.get_tool_key(tool_type.id, md5_hash(one.name))
            new_tools[tool_key] = GptsTools(
                name=one.name,
                desc=one.description,
                tool_key=tool_key,
                is_preset=ToolPresetType.MCP.value,
                api_params=self.convert_input_schema(one.inputSchema),
                extra=one.model_dump_json(),
                type=tool_type.id,
            )

        # 2. get need add or update or delete tool
        need_delete_tool = []  # list[int]
        need_update_tool = []  # list[GptsTools]
        for one in old_tools:
            if one.tool_key not in new_tools:
                # 需要删除的工具
                logger.info(f'delete mcp tool: {one.name}')
                need_delete_tool.append(one.id)
            else:
                logger.info(f'update mcp tool: {one.name}')
                one.name = new_tools[one.tool_key].name
                one.desc = new_tools[one.tool_key].desc
                one.tool_key = new_tools[one.tool_key].tool_key
                one.api_params = new_tools[one.tool_key].api_params
                one.extra = new_tools[one.tool_key].extra
                need_update_tool.append(one)
                del new_tools[one.tool_key]
        need_add_tool = list(new_tools.values())

        # 3. update db
        if need_delete_tool:
            GptsToolsDao.delete_tool_by_ids(need_delete_tool)
        if need_update_tool:
            GptsToolsDao.update_tool_list(need_update_tool)
        if need_add_tool:
            GptsToolsDao.update_tool_list(need_add_tool)

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

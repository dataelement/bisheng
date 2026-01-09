import asyncio
import json
from typing import Optional, List

import yaml
from fastapi import Request
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, ConfigDict

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.utils import get_url_content
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.errcode.tool import ToolTypeNotExistsError, ToolTypeRepeatError, ToolTypeNameError, \
    ToolTypeIsPresetError, ToolSchemaDownloadError, ToolSchemaEmptyError, ToolSchemaParseError, ToolSchemaServerError, \
    ToolMcpSchemaError
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum, GroupResource
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.user_group import UserGroupDao
from bisheng.mcp_manage.manager import ClientManager
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao, GptsTools, GptsToolsType, GptsToolsTypeRead
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng.utils import md5_hash, get_request_ip
from bisheng.utils.mask_data import JsonFieldMasker
from bisheng_langchain.gpts.load_tools import load_tools


class ToolServices(BaseModel):
    """ Tool service class """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Optional[Request] = None
    login_user: Optional[UserPayload] = None

    async def get_tool_list(self, is_preset: Optional[int] = None) -> List[GptsToolsTypeRead]:
        """ Get a list of tools visible to users """
        # Get Tool Categories Visible to Users
        tool_type_ids_extra = []
        if is_preset != ToolPresetType.PRESET.value:
            # When getting a list of custom tools, you need to include a list of tools available to the user
            access_resources = await self.login_user.aget_user_access_resource_ids([AccessType.GPTS_TOOL_READ])
            if access_resources:
                tool_type_ids_extra = [int(access) for access in access_resources]
        if is_preset is None:
            # Get a list of all tools visible to the user
            all_tool_type = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, tool_type_ids_extra)
        elif is_preset == ToolPresetType.PRESET.value:
            # Get a list of preset tools
            all_tool_type = await GptsToolsDao.aget_preset_tool_type()
        else:
            # Get a list of custom tools visible to users
            all_tool_type = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, tool_type_ids_extra, False,
                                                                   ToolPresetType(is_preset))
        tool_type_id = [one.id for one in all_tool_type]
        res: List[GptsToolsTypeRead] = []
        tool_type_children = {}
        for one in all_tool_type:
            tool_type_id.append(one.id)
            tool_type_children[one.id] = []
            res.append(GptsToolsTypeRead.model_validate(one))

        # Get the list of tools under the corresponding category
        tool_list = await GptsToolsDao.aget_list_by_type(tool_type_id)
        for one in tool_list:
            tool_type_children[one.type].append(one)

        # check write permission
        write_tool_type = None
        for one in res:
            if self.login_user.is_admin() or one.user_id == self.login_user.user_id:
                one.write = True
            else:
                if write_tool_type is None:
                    write_resources = await self.login_user.aget_user_access_resource_ids([AccessType.GPTS_TOOL_WRITE])
                    write_tool_type = {int(x): True for x in write_resources}
                one.write = write_tool_type.get(one.id, False)
            one.children = tool_type_children.get(one.id, [])

            # Data desensitization
            one.mask_sensitive_data()

        return res

    async def add_tools(self, req: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """ Add custom tool """
        # Try to parse theopenapi schemaSee if it can be parsed normally, Save if not possible Do not allow to save
        if req.is_preset == ToolPresetType.API.value:
            await self.parse_openapi_schema('', req.openapi_schema)
        elif req.is_preset == ToolPresetType.MCP.value:
            await self.parse_mcp_schema(req.openapi_schema)

        req.id = None
        if req.name.__len__() > 1000 or req.name.__len__() == 0:
            raise ToolTypeNameError()
        # Determine if the category already exists
        tool_type = await GptsToolsDao.get_one_tool_type_by_name(self.login_user.user_id, req.name)
        if tool_type:
            raise ToolTypeRepeatError()
        req.user_id = self.login_user.user_id

        for one in req.children:
            one.id = None
            one.user_id = self.login_user.user_id
            one.is_delete = 0
            one.is_preset = req.is_preset

        tool_extra = {"api_location": req.api_location, "parameter_name": req.parameter_name}
        req.extra = json.dumps(tool_extra, ensure_ascii=False)
        # Add Tool Category and Corresponding Tools List
        res = await GptsToolsDao.insert_tool_type(req)

        self.add_gpts_tools_hook(self.request, self.login_user, res)
        return res

    @classmethod
    def add_gpts_tools_hook(cls, request: Request, user: UserPayload, gpts_tool_type: GptsToolsTypeRead) -> bool:
        """ After adding custom toolshookFunction """
        # Query the user group the user belongs to under
        user_group = UserGroupDao.get_user_group(user.user_id)
        group_ids = []
        if user_group:
            # Batch Insert Custom Tools into Correlation Table
            batch_resource = []
            for one in user_group:
                group_ids.append(one.group_id)
                batch_resource.append(GroupResource(
                    group_id=one.group_id,
                    third_id=gpts_tool_type.id,
                    type=ResourceTypeEnum.GPTS_TOOL.value))
            GroupResourceDao.insert_group_batch(batch_resource)
        AuditLogService.create_tool(user, get_request_ip(request), group_ids, gpts_tool_type)
        return True

    async def update_tool_config(self, tool_type_id: int, extra: dict) -> bool:
        # Get Tool Categories
        tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id)
        if not tool_type or tool_type.is_preset != ToolPresetType.PRESET.value:
            raise NotFoundError()

        if not await self.login_user.async_access_check(tool_type.user_id, str(tool_type.id),
                                                        AccessType.GPTS_TOOL_WRITE):
            raise UnAuthorizedError()

        if tool_type.extra is None:
            tool_type.extra = '{}'

        json_masker = JsonFieldMasker()

        old_config = json.loads(tool_type.extra)
        # special handle dall-e config update。 Wait until you unify this configuration with the configuration logic of other tools (the configuration parameters remain unchanged), and then delete this special processing logic
        if tool_type.name == "Dalle3-	painting;":
            # Instructions not toggledtab. Just changed the configuration
            if ("azure_endpoint" in old_config and "azure_endpoint" in extra) or (
                    "azure_endpoint" not in old_config and "azure_endpoint" not in extra
            ):
                # Update the configuration of all tools under the Tools category
                merge_extra = json_masker.update_json_with_masked(old_config, extra)
                merge_extra = json.dumps(merge_extra, ensure_ascii=False)
            elif not old_config:
                # The description has not been configured before, it is now configured
                merge_extra = json.dumps(extra, ensure_ascii=False)
            else:
                # Instructions switchedtab, you need to overwrite the previous configuration
                merge_extra = json.dumps(extra, ensure_ascii=False)
        else:
            # Update the configuration of all tools under the Tools category
            merge_extra = json_masker.update_json_with_masked(old_config, extra)
            merge_extra = json.dumps(merge_extra, ensure_ascii=False)
        await GptsToolsDao.update_tools_extra(tool_type_id, merge_extra)
        return True

    @staticmethod
    async def parse_openapi_schema(download_url: str, file_content: str) -> GptsToolsTypeRead:
        if download_url:
            try:
                file_content = await get_url_content(download_url)
            except Exception as e:
                logger.exception(f'file {download_url} download error')
                raise ToolSchemaDownloadError(exception=e)
        if not file_content:
            raise ToolSchemaEmptyError()
        # Depending on the content of the document, is it possible to`{`At the beginning, what analytical method is used to determine
        try:
            if file_content.startswith('{'):
                res = json.loads(file_content)
            else:
                res = yaml.safe_load(file_content)
        except Exception as e:
            logger.exception(f'openapi schema parse error {e}')
            raise ToolSchemaParseError(exception=e)

        #  analyzingopenapi schemaConvert to Helper Tool Format
        try:
            schema = OpenApiSchema(res)
            schema.parse_server()
            if not schema.default_server.startswith(('http', 'https')):
                raise ToolSchemaServerError(data={"url": schema.default_server})
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
            # Parsing to get all theapi
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
        except BaseErrorCode as e:
            raise e
        except Exception as e:
            logger.exception(f'openapi schema parse error {e}')
            raise ToolSchemaParseError(exception=e)

    @staticmethod
    async def parse_mcp_schema(file_content: str) -> GptsToolsTypeRead:
        try:
            result = json.loads(file_content)
            mcp_servers = result['mcpServers']
        except Exception as e:
            logger.exception(f'mcp tool schema parse error {e}')
            raise ToolMcpSchemaError(exception=e)
        tool_type = None
        for key, value in mcp_servers.items():
            # analyzingmcpService Config
            tool_type = GptsToolsTypeRead(name=value.get('name', ''),
                                          server_host=value.get('url', ''),
                                          description=value.get('description', ''),
                                          is_preset=ToolPresetType.MCP.value,
                                          openapi_schema=file_content,
                                          children=[])
            # Instantiatemcpservice object, getting a list of tools
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
            raise ToolMcpSchemaError()
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

        # Get old under this categoryAPIVertical
        old_tool_list = await GptsToolsDao.aget_list_by_type([exist_tool_type.id])
        # List of tools that need to be removed
        delete_tool_id_list = []
        # List of tools that need to be updated
        update_tool_list = []
        for one in old_tool_list:
            # Explain this tool Removal required
            if children_map.get(one.name) is None:
                delete_tool_id_list.append(one.id)
            else:
                # Explain that this tool needs to be updated
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

        await GptsToolsDao.update_tool_type(exist_tool_type, delete_tool_id_list,
                                            add_children, update_tool_list)

        children = await GptsToolsDao.aget_list_by_type([exist_tool_type.id])
        return GptsToolsTypeRead(**exist_tool_type.model_dump(), children=children)

    async def update_tools(self, req: GptsToolsTypeRead) -> GptsToolsTypeRead:
        """
        Updating tool categories, including updating tool category names and deletions, adding tool categoryAPI
        """
        # Try to parse theopenapi schemaSee if it can be parsed normally, Save if not possible Do not allow to save
        if req.is_preset == ToolPresetType.API.value:
            await self.parse_openapi_schema('', req.openapi_schema)
        elif req.is_preset == ToolPresetType.MCP.value:
            await self.parse_mcp_schema(req.openapi_schema)

        exist_tool_type = await GptsToolsDao.aget_one_tool_type(req.id)
        if not exist_tool_type:
            raise ToolTypeNotExistsError()
        if req.name.__len__() > 1000 or req.name.__len__() == 0:
            raise ToolTypeNameError()

        #  Determine if the tool category name is a duplicate
        tool_type = await GptsToolsDao.get_one_tool_type_by_name(self.login_user.user_id, req.name)
        if tool_type and tool_type.id != exist_tool_type.id:
            raise ToolTypeRepeatError()
        # Determine if there are update permissions
        if not await self.login_user.async_access_check(exist_tool_type.user_id, str(exist_tool_type.id),
                                                        AccessType.GPTS_TOOL_WRITE):
            raise UnAuthorizedError()

        res = await self._update_gpts_tools(exist_tool_type, req)
        await self.update_tool_hook(self.request, self.login_user, exist_tool_type)
        return res

    @classmethod
    async def update_tool_hook(cls, request: Request, user: UserPayload, exist_tool_type):
        groups = await GroupResourceDao.aget_resource_group(ResourceTypeEnum.GPTS_TOOL, exist_tool_type.id)
        group_ids = [int(one.group_id) for one in groups]
        await asyncio.to_thread(AuditLogService.update_tool, user, get_request_ip(request), group_ids, exist_tool_type)

    async def delete_tools(self, tool_type_id: int) -> bool:
        """ Delete Tool Category """
        exist_tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id)
        if not exist_tool_type:
            return True
        if exist_tool_type.is_preset == ToolPresetType.PRESET.value:
            raise ToolTypeIsPresetError()
        # Determine if there are update permissions
        if not await self.login_user.async_access_check(exist_tool_type.user_id, str(exist_tool_type.id),
                                                        AccessType.GPTS_TOOL_WRITE):
            raise UnAuthorizedError()

        await GptsToolsDao.delete_tool_type(tool_type_id)
        await asyncio.to_thread(self.delete_tool_hook, self.request, self.login_user, exist_tool_type)
        return True

    @classmethod
    def delete_tool_hook(cls, request, user: UserPayload, gpts_tool_type) -> bool:
        """ After deleting the customizerhookFunction """
        logger.info(f"delete_gpts_tool_hook id: {gpts_tool_type.id}, user: {user.user_id}")
        GroupResourceDao.delete_group_resource_by_third_id(gpts_tool_type.id, ResourceTypeEnum.GPTS_TOOL)
        groups = GroupResourceDao.get_resource_group(ResourceTypeEnum.GPTS_TOOL, gpts_tool_type.id)
        group_ids = [int(one.group_id) for one in groups]
        AuditLogService.delete_tool(user, get_request_ip(request), group_ids, gpts_tool_type)
        return True

    async def refresh_all_mcp(self) -> list[str]:
        """ return mcp server error msg """
        # get user all mcp tool
        tool_types = await GptsToolsDao.aget_user_tool_type(self.login_user.user_id, is_preset=ToolPresetType.MCP)
        if not tool_types:
            return []

        tools = await GptsToolsDao.aget_list_by_type(tool_type_ids=[one.id for one in tool_types])
        tools_map = {}
        for one in tools:
            if one.type not in tools_map:
                tools_map[one.type] = []
            tools_map[one.type].append(one)
        error_name = []
        for one in tool_types:
            try:
                await self.refresh_mcp_tools(one, tools_map.get(one.id, []))
            except Exception as e:
                logger.exception(f'{one.name} tool refresh failed')
                error_name.append(one.name)
        return error_name

    async def refresh_mcp_tools(self, tool_type: GptsToolsType, old_tools: list[GptsTools]):
        """ refresh mcp tools """
        # 1. get all new tools
        # Instantiatemcpservice object, getting a list of tools
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
        """ TukarmcpInput parameters for the tool Formatting for custom tools"""
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
        """ InisialisasiLinsight Default Tools, The special point is that the parameters initialized by the local file tool are not fixed, but are determined during rerun """
        # Tools for loading local file operations
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

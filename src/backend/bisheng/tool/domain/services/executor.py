import functools
import json
from typing import Any, Annotated, Optional, Dict, List

from langchain_core.tools import BaseTool, ArgsSchema
from pydantic import Field, SkipValidation

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, StatusEnum, ApplicationTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import ToolInvocationEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, Knowledge
from bisheng.mcp_manage.langchain.tool import McpTool
from bisheng.mcp_manage.manager import ClientManager
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.langchain.knowledge import KnowledgeRagTool
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao, GptsTools, GptsToolsType
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools


def wrapper_tool(func):
    @functools.wraps(func)
    async def inner(*args, **kwargs):
        # Here you can add logic to record tool usage
        self: ToolExecutor = args[0]
        status = StatusEnum.SUCCESS
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            status = StatusEnum.FAILED
            raise e
        finally:
            await telemetry_service.log_event(**self.get_invoke_log_data(status))

    return inner


def wrapper_tool_sync(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        # Here you can add logic to record tool usage
        self: ToolExecutor = args[0]
        status = StatusEnum.SUCCESS
        try:
            return func(*args, **kwargs)
        except Exception as e:
            status = StatusEnum.FAILED
            raise e
        finally:
            # 记录Telemetry日志
            telemetry_service.log_event_sync(**self.get_invoke_log_data(status))

    return inner


class ToolExecutor(BaseTool):
    # must provide fields for telemetry logging
    app_id: str = Field(..., description="Application Identifier")
    app_name: str = Field(..., description="Application Name")
    app_type: ApplicationTypeEnum = Field(..., description="Application Type")
    user_id: int = Field(..., description="Invoke User ID")

    # bisheng tool fields
    tool_id: int = Field(..., description="Tool ID")
    tool_is_preset: int = Field(..., description="kind of the Tool, api、mcp、preset")
    tool_name: str = Field(..., description="Tool Name")

    # langchain tool fields
    name: str = Field(..., description="Tool Name for llm")
    description: str = Field(..., description="Tool Description for llm")
    args_schema: Annotated[Optional[ArgsSchema], SkipValidation()] = Field(
        default=None, description="The tool schema."
    )
    tool_instance: BaseTool = Field(..., description="Langchain Tool Instance")

    @classmethod
    def init_by_tool_instance(cls, base_tool: BaseTool, tool: GptsTools, *, app_id: str, app_name: str,
                              app_type: ApplicationTypeEnum, user_id: int) -> BaseTool:
        return cls(name=base_tool.name, description=base_tool.description, args_schema=base_tool.args_schema,
                   tool_instance=base_tool,
                   app_id=app_id, app_name=app_name, app_type=app_type, user_id=user_id,
                   tool_id=tool.id, tool_is_preset=tool.is_preset, tool_name=tool.name)

    @staticmethod
    def parse_preset_tool_params(tool: GptsTools) -> Dict:
        """ parse tool init params """
        # 特殊处理下bisheng_code_interpreter的参数
        if tool.tool_key == 'bisheng_code_interpreter':
            params = {}
            if tool.extra:
                if isinstance(tool.extra, str):
                    params = json.loads(tool.extra)
                elif isinstance(tool.extra, dict):
                    params = tool.extra
            return {'minio': settings.get_minio_conf().model_dump(), **params}
        if not tool.extra:
            return {}
        params = json.loads(tool.extra)
        return params

    @staticmethod
    def parse_api_tool_params(tool: GptsTools, tool_type: GptsToolsType, **kwargs) -> Dict:
        """ parse tool init params """
        extra_json = json.loads(tool.extra) if tool.extra else {}
        extra_json.update(json.loads(tool_type.extra) if tool_type.extra else {})
        params = OpenApiSchema.parse_openapi_tool_params(tool.name, tool.desc, extra_json,
                                                         tool_type.server_host,
                                                         tool_type.auth_method,
                                                         tool_type.auth_type,
                                                         tool_type.api_key)
        params.update(kwargs)
        return params

    @classmethod
    def _init_preset_tool(cls, tool: GptsTools, tool_type: GptsToolsType, **kwargs) -> BaseTool:
        tool_name_param = {
            tool.tool_key: cls.parse_preset_tool_params(tool)
        }
        tool_langchain = load_tools(tool_params=tool_name_param, **kwargs)
        if not tool_langchain:
            raise ValueError(f"Failed to load preset tool: {tool.tool_key}")
        return tool_langchain[0]

    @classmethod
    def _init_api_tool(cls, tool: GptsTools, tool_type: GptsToolsType, **kwargs) -> BaseTool:
        tool_params = cls.parse_api_tool_params(tool, tool_type, **kwargs)
        return OpenApiTools.get_api_tool(tool.tool_key, **tool_params)

    @classmethod
    def _init_mcp_tool(cls, tool: GptsTools, tool_type: GptsToolsType, **kwargs) -> BaseTool:
        mcp_client = ClientManager.sync_connect_mcp_from_json(tool_type.openapi_schema)
        input_schema = json.loads(tool.extra)
        return McpTool.get_mcp_tool(name=tool.tool_key, description=tool.desc, mcp_client=mcp_client,
                                    mcp_tool_name=tool.name, arg_schema=input_schema['inputSchema'],
                                    **kwargs)

    @classmethod
    def _init_by_tool_and_type(cls, tool: GptsTools, tool_type: GptsToolsType, *, app_id: str, app_name: str,
                               app_type: ApplicationTypeEnum, user_id: int, **kwargs) -> BaseTool:
        if tool.is_preset == ToolPresetType.PRESET.value:
            tool_instance = cls._init_preset_tool(tool, tool_type, **kwargs)
        elif tool.is_preset == ToolPresetType.API.value:
            tool_instance = cls._init_api_tool(tool, tool_type, **kwargs)
        elif tool.is_preset == ToolPresetType.MCP.value:
            tool_instance = cls._init_mcp_tool(tool, tool_type, **kwargs)
        else:
            raise ValueError(f"Unsupported tool preset type: {tool.is_preset}")
        return cls.init_by_tool_instance(base_tool=tool_instance, tool=tool, app_id=app_id,
                                         app_name=app_name, app_type=app_type, user_id=user_id)

    @classmethod
    async def init_by_tool_id(cls, tool_id: int = None, tool: GptsTools = None, *, app_id: str, app_name: str,
                              app_type: ApplicationTypeEnum, user_id: int, **kwargs) -> BaseTool:
        if not tool_id and not tool:
            raise ValueError("Either tool_id or tool must be provided.")
        if not tool:
            tool = await GptsToolsDao.aget_one_tool(tool_id=tool_id)
            if not tool:
                raise ValueError(f"Tool with id {tool_id} not found.")
        tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id=tool.type)
        if not tool_type:
            raise ValueError(f"Tool type with id {tool.type} not found.")
        return cls._init_by_tool_and_type(tool=tool, tool_type=tool_type, app_id=app_id, app_name=app_name,
                                          app_type=app_type, user_id=user_id, **kwargs)

    @classmethod
    def _init_tools(cls, tools: List[GptsTools], tool_types_map: Dict[int, GptsToolsType], *,
                    app_id: str, app_name: str, app_type: ApplicationTypeEnum,
                    user_id: int, **kwargs) -> List[BaseTool]:
        result = []
        for tool in tools:
            tool_type = tool_types_map.get(tool.type)
            if not tool_type:
                raise ValueError(f"Tool type with id {tool.type} not found.")
            result.append(
                cls._init_by_tool_and_type(tool=tool, tool_type=tool_type, app_id=app_id,
                                           app_name=app_name, app_type=app_type, user_id=user_id, **kwargs)
            )
        return result

    @classmethod
    async def init_by_tool_ids(cls, tool_ids: list[int], *, app_id: str, app_name: str, app_type: ApplicationTypeEnum,
                               user_id: int, **kwargs) -> List[BaseTool]:
        tools = await GptsToolsDao.aget_list_by_ids(tool_ids)
        tool_type_ids = [tool.type for tool in tools]
        tool_types = await GptsToolsDao.aget_all_tool_type(list(set(tool_type_ids)))
        tool_type_map = {tool_type.id: tool_type for tool_type in tool_types}

        return cls._init_tools(tools, tool_type_map, app_id=app_id, app_name=app_name, app_type=app_type,
                               user_id=user_id, **kwargs)

    @classmethod
    def init_by_tool_ids_sync(cls, tool_ids: list[int], app_id: str, app_name: str, app_type: ApplicationTypeEnum,
                              user_id: int, **kwargs) -> List[BaseTool]:
        tools = GptsToolsDao.get_list_by_ids(tool_ids)
        tool_type_ids = [tool.type for tool in tools]
        tool_types = GptsToolsDao.get_all_tool_type(list(set(tool_type_ids)))
        tool_type_map = {tool_type.id: tool_type for tool_type in tool_types}

        return cls._init_tools(tools, tool_type_map, app_id=app_id, app_name=app_name, app_type=app_type,
                               user_id=user_id, **kwargs)

    @classmethod
    def init_by_tool_id_sync(cls, tool_id: int, *, app_id: str, app_name: str, app_type: ApplicationTypeEnum,
                             user_id: int, **kwargs) -> BaseTool:
        tool = GptsToolsDao.get_one_tool(tool_id=tool_id)
        if not tool:
            raise ValueError(f"Tool with id {tool_id} not found.")
        tool_type = GptsToolsDao.get_one_tool_type(tool_type_id=tool.type)
        if not tool_type:
            raise ValueError(f"Tool type with id {tool.type} not found.")

        return cls._init_by_tool_and_type(tool=tool, tool_type=tool_type, app_id=app_id, app_name=app_name,
                                          app_type=app_type, user_id=user_id, **kwargs)

    @classmethod
    def _init_knowledge_rag_tool(cls, knowledge: Knowledge, **kwargs) -> BaseTool:
        return KnowledgeRagTool.init_knowledge_rag_tool(name=f'knowledge_{knowledge.id}',
                                                        description=f'{knowledge.name}:{knowledge.description}',
                                                        **kwargs)

    @classmethod
    async def init_knowledge_tool(cls, invoke_user_id: int, knowledge_id: int, **kwargs) -> BaseTool:
        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id=knowledge_id)
        if not knowledge:
            raise ValueError(f"Knowledge with id {knowledge_id} not found.")
        vector_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(invoke_user_id, knowledge)
        es_client = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge)
        return cls._init_knowledge_rag_tool(knowledge=knowledge, vector_retriever=vector_client.as_retriever(),
                                            elastic_retriever=es_client.as_retriever(), **kwargs)

    @classmethod
    def init_knowledge_tool_sync(cls, invoke_user_id: int, knowledge_id: int, **kwargs) -> BaseTool:
        knowledge = KnowledgeDao.query_by_id(knowledge_id=knowledge_id)
        if not knowledge:
            raise ValueError(f"Knowledge with id {knowledge_id} not found.")
        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(invoke_user_id, knowledge)
        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge)
        return cls._init_knowledge_rag_tool(knowledge, vector_retriever=vector_client.as_retriever(),
                                            elastic_retriever=es_client.as_retriever(), **kwargs)

    @classmethod
    def init_tmp_knowledge_tool_sync(cls, **kwargs) -> BaseTool:
        return KnowledgeRagTool.init_knowledge_rag_tool(**kwargs)

    @wrapper_tool_sync
    def _run(self, *args, **kwargs) -> Any:
        return self.tool_instance._run(*args, **kwargs)

    @wrapper_tool
    async def _arun(self, *args, **kwargs) -> Any:
        return self.tool_instance._arun(*args, **kwargs)

    def get_invoke_log_data(self, status: StatusEnum):
        # 记录Telemetry日志
        return {
            "user_id": self.user_id,
            "event_type": BaseTelemetryTypeEnum.TOOL_INVOKE,
            "trace_id": trace_id_var.get(),
            "event_data": ToolInvocationEventData(
                app_id=self.app_id,
                app_name=self.app_name,
                app_type=self.app_type,
                tool_id=self.tool_id,
                tool_name=self.tool_name,
                tool_type=self.tool_is_preset,
                status=status
            )}

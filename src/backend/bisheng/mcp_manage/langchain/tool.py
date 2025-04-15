import asyncio
from typing import Any, Type

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model, BaseModel, ConfigDict

from bisheng.mcp_manage.clients.base import BaseMcpClient


def convert_openai_params_to_model(params: list[dict]) -> Type[BaseModel]:
    model_params = {}
    for one in params:
        field_type = one['schema']['type']
        if field_type == 'number':
            field_type = float
        elif field_type == 'integer':
            field_type = int
        elif field_type == 'string':
            field_type = str
        elif field_type == 'boolean':
            field_type = bool
        elif field_type == 'array':
            field_type = list
        elif field_type in {'object', 'dict'}:
            param_object_param = {}
            for param in one['schema']['properties'].keys():
                field_type = one['schema']['properties'][param]['type']
                if field_type == 'number':
                    field_type = float
                elif field_type == 'integer':
                    field_type = int
                elif field_type == 'string':
                    field_type = str
                elif field_type == 'boolean':
                    field_type = bool
                elif field_type == 'array':
                    field_type = list
                param_object_param[param] = (
                    field_type,
                    Field(description=one['schema']['properties'][param]['description']))
            param_model = create_model(
                param,
                __module__='bisheng.mcp_manage.langchain.tool',
                **param_object_param)
            field_type = param_model
        else:
            raise Exception(f'schema type is not support: {field_type}')
        model_params[one['name']] = (field_type, Field(description=one['description']))
    return create_model('InputArgs',
                        __module__='bisheng.mcp_manage.langchain.tool',
                        __base__=BaseModel,
                        **model_params)


class McpTool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    mcp_client: BaseMcpClient
    mcp_tool_name: str

    def run(self, *args, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(self._arun(**kwargs), loop)
        return future.result()

    async def arun(self, *args, **kwargs: Any) -> Any:
        """Use the tool asynchronously."""
        print(f"================ {args}| {kwargs}")
        resp = await self.mcp_client.call_tool(self.mcp_tool_name, kwargs)
        return resp

    @classmethod
    def get_mcp_tool(cls, name: str, description: str, mcp_client: BaseMcpClient,
                     mcp_tool_name: str, arg_schema: Any, **kwargs) -> StructuredTool:
        """Get a tool from the class."""
        c = cls(name=name, description=description, mcp_client=mcp_client,
                mcp_tool_name=mcp_tool_name)
        return StructuredTool(name=c.name,
                              description=c.description,
                              func=c.run,
                              coroutine=c.arun,
                              args_schema=arg_schema,
                              **kwargs)

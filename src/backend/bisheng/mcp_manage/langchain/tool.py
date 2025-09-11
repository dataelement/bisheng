import asyncio
import concurrent
import concurrent.futures
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

from bisheng.mcp_manage.clients.base import BaseMcpClient
from bisheng_langchain.utils.openapi import convert_openapi_field_value


class McpTool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    mcp_client: BaseMcpClient
    mcp_tool_name: str
    arg_schema: dict = {}

    def parse_kwargs_schema(self, kwargs: dict) -> None | dict:
        """convert the kwargs field value"""
        if not kwargs:
            return None
        for k, v in kwargs.items():
            k_type = self.arg_schema.get("properties", {}).get(k, {}).get("type")
            kwargs[k] = convert_openapi_field_value(v, k_type)
        return kwargs

    def run(self, *args, **kwargs: Any) -> Any:
        # todo call async method better when using in event pool
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, self.arun(*args, **kwargs))
            resp = future.result()
        return resp

    async def arun(self, *args, **kwargs: Any) -> Any:
        """Use the tool asynchronously."""
        kwargs = self.parse_kwargs_schema(kwargs)
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

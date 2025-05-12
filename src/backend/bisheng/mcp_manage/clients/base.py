from abc import abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from mcp import ClientSession


class BaseMcpClient(object):
    """
    Base class for MCP clients.
    """

    def __init__(self, **kwargs):
        self.exit_stack = AsyncExitStack()

        self.client_session: ClientSession | None = None

    @abstractmethod
    async def get_transport(self):
        raise NotImplementedError("get_mcp_client_transport() must be implemented in subclasses.")

    @asynccontextmanager
    async def initialize(self):
        """
        Initialize the client.
        """
        async with self.get_transport() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self):
        async with self.initialize() as client_session:
            tools = await client_session.list_tools()
        return tools.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """
        Call a tool.
        """
        async with self.initialize() as client_session:
            try:
                resp = await client_session.call_tool(name, arguments)
            except Exception as e:
                return f"Tool call failed: {str(e)}"
        return resp.model_dump_json()

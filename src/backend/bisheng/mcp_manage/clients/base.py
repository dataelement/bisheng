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

    async def get_mcp_client_transport(self):
        raise NotImplementedError("get_mcp_client_transport() must be implemented in subclasses.")

    @asynccontextmanager
    async def initialize(self):
        """
        Initialize the client.
        """
        async with self.get_mcp_client_transport() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self):
        async with self.initialize() as client_session:
            tools = await client_session.list_tools()
        return tools.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        """
        Call a tool.
        """
        async with self.initialize() as client_session:
            resp = await client_session.call_tool(name, arguments)
        return resp

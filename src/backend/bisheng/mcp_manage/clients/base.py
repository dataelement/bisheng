from contextlib import AsyncExitStack
from typing import Any

from anyio import ClosedResourceError
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


    async def initialize(self):
        """
        Initialize the client.
        """
        if not self.client_session:
            read, write = await self.get_mcp_client_transport()
            self.client_session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
        try:
            await self.client_session.initialize()
        except ClosedResourceError as e:
            # reconnect sse server
            await self.close()
            read, write = await self.get_mcp_client_transport()
            self.client_session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.client_session.initialize()

    async def list_tools(self):
        tools = await self.client_session.list_tools()
        return tools.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        """
        Call a tool.
        """
        return await self.client_session.call_tool(name, arguments)

    async def close(self):
        print("!!!!!!!!!!!!!!!!!! close !!!!!!!!!!!!!!!")
        await self.exit_stack.aclose()
        self.client_session = None

from contextlib import asynccontextmanager

from mcp.client.stdio import stdio_client, StdioServerParameters

from bisheng.mcp_manage.clients.base import BaseMcpClient


class StdioClient(BaseMcpClient):
    """
    SSE client for connecting to the mcp server.
    """

    def __init__(self, **kwargs: dict):
        """
        Initialize the SSE client.

        :param url: The URL of the SSE server.
        """
        super().__init__()
        self.server_params = StdioServerParameters(**kwargs)

    @asynccontextmanager
    async def get_transport(self):
        """
        Initialize the SSE client.
        """
        async with stdio_client(server=self.server_params) as (read, write):
            yield read, write

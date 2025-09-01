from contextlib import asynccontextmanager

from mcp.client.streamable_http import streamablehttp_client

from bisheng.mcp_manage.clients.base import BaseMcpClient


class StreamableClient(BaseMcpClient):
    """
    SSE client for connecting to the mcp server.
    """

    def __init__(self, url: str, **kwargs):
        """
        Initialize the streamable http client.

        :param url: The URL of the streamable server.
        """
        super().__init__()
        self.url = url
        self.kwargs = kwargs

    @asynccontextmanager
    async def get_transport(self):
        """
        Initialize the SSE client.
        """
        async with streamablehttp_client(url=self.url, **self.kwargs) as (read, write, _):
            yield read, write

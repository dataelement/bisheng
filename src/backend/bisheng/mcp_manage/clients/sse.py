from mcp.client.sse import sse_client

from bisheng.mcp_manage.clients.base import BaseMcpClient


class SseClient(BaseMcpClient):
    """
    SSE client for connecting to the mcp server.
    """

    def __init__(self, url: str):
        """
        Initialize the SSE client.

        :param url: The URL of the SSE server.
        """
        super().__init__()
        self.url = url

    async def get_mcp_client_transport(self):
        """
        Initialize the SSE client.
        """
        return await self.exit_stack.enter_async_context(sse_client(url=self.url))

    def connect(self):
        """
        Connect to the SSE server.
        """
        pass  # Implement the connection logic here
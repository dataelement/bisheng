import json

from bisheng.mcp_manage.clients.base import BaseMcpClient
from bisheng.mcp_manage.clients.sse import SseClient
from bisheng.mcp_manage.clients.stdio import StdioClient
from bisheng.mcp_manage.constant import McpClientType


class ClientManager:

    @classmethod
    async def connect_mcp_from_json(cls, client_json: dict | str):
        """ 获取对应配置下的的mcp连接 """
        return cls.sync_connect_mcp_from_json(client_json)

    @classmethod
    def sync_connect_mcp_from_json(cls, client_json: dict | str) -> BaseMcpClient:
        """ 获取对应配置下的的mcp连接 """
        if isinstance(client_json, str):
            client_json = json.loads(client_json)

        mcp_servers = client_json['mcpServers']
        client_type = McpClientType.SSE.value
        client_kwargs = {}

        for _, kwargs in mcp_servers.items():
            if 'command' in kwargs:
                client_type = McpClientType.STDIO.value
            kwargs.pop('name', '')
            kwargs.pop('description', '')
            client_kwargs = kwargs
            break
        return cls.sync_connect_mcp(client_type, **client_kwargs)


    @classmethod
    async def connect_mcp(cls, client_type: str, **kwargs) -> BaseMcpClient:
        """ 获取对应url的mcp连接 """
        # 初始化对应的client
        return cls.sync_connect_mcp(client_type, **kwargs)

    @classmethod
    def sync_connect_mcp(cls, client_type: str, **kwargs) -> BaseMcpClient:
        # 初始化对应的client
        if client_type == McpClientType.SSE.value:
            client = SseClient(**kwargs)
        elif client_type == McpClientType.STDIO.value:
            client = StdioClient(**kwargs)
        else:
            raise ValueError(f'client_type {client_type} not supported')
        return client

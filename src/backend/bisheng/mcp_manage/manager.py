from typing import Dict

from bisheng.api.utils import md5_hash
from bisheng.mcp_manage.clients.base import BaseMcpClient
from bisheng.mcp_manage.clients.sse import SseClient
from bisheng.mcp_manage.constant import McpClientType


class ClientManager:
    # 缓存对应的mcp连接
    client_map: Dict[str, BaseMcpClient] = {}

    @classmethod
    async def connect_mcp(cls, client_type: str, **kwargs) -> BaseMcpClient:
        """ 获取对应url的mcp连接 """
        # 初始化对应的client
        return cls.sync_connect_mcp(client_type, **kwargs)

    @classmethod
    def sync_connect_mcp(cls, client_type: str, **kwargs) -> BaseMcpClient:
        # 初始化对应的client
        client_key = md5_hash(f'{client_type}:{kwargs}')
        if cls.client_map.get(client_key) is None:
            if client_type == McpClientType.SSE.value:
                client = SseClient(**kwargs)
            else:
                raise ValueError(f'client_type {client_type} not supported')
            cls.client_map[client_key] = client
        else:
            client = cls.client_map[client_key]

        return client

    @classmethod
    async def disconnect_mcp(cls, client_type: str, **kwargs):
        """ 释放对应url的mcp连接 """
        client_key = md5_hash(f'{client_type}:{kwargs}')
        if client_key not in cls.client_map:
            return
        del cls.client_map[client_key]

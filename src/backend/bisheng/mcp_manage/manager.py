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
        client_key = md5_hash(f'{client_type}:{kwargs}')
        if cls.client_map.get(client_key) is None:
            if client_type == McpClientType.SSE.value:
                client = SseClient(**kwargs)
            else:
                raise ValueError(f'client_type {client_type} not supported')
            cls.client_map[client_key] = client
        else:
            client = cls.client_map[client_key]

        # 判断对应的client是否还处于链接状态
        await client.initialize()

        return client

    @classmethod
    async def disconnect_mcp(cls, client_type: str, **kwargs):
        """ 释放对应url的mcp连接 """
        client_key = md5_hash(f'{client_type}:{kwargs}')
        if client_key not in cls.client_map:
            return
        client = cls.client_map[client_key]
        await client.close()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """ 释放所有的连接 """
        for client_key in self.client_map.keys():
            client = self.client_map[client_key]
            await client.close()

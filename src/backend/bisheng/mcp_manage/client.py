from typing import Dict

from mcp import ClientSession
from mcp.client.stdio import stdio_client

class ClientManager:

    # 缓存对应的mcp连接
    client_map: Dict[str, ClientSession] = {}

    def __init__(self, client):
        self.client = client

    def get_client(self):
        return self.client
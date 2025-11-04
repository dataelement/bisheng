import logging
from abc import ABC

from bisheng.core.context import BaseContextManager
from bisheng.core.context.base import T
from bisheng.core.external.http_client.client import AsyncHttpClient

logger = logging.getLogger(__name__)


class HttpClientManager(BaseContextManager[AsyncHttpClient], ABC):
    """HTTP 客户端管理器

    继承自 BaseContextManager，提供 HTTP 客户端的生命周期管理
    支持懒加载和缓存
    """

    name = 'http_client'

    def __init__(self):
        super().__init__()

    async def _async_initialize(self) -> AsyncHttpClient:
        """异步初始化 HTTP 客户端"""
        http_client = AsyncHttpClient()
        await http_client.get_aiohttp_client()
        return http_client

    def _sync_initialize(self) -> T:
        pass

    async def _async_cleanup(self) -> None:
        """异步清理 HTTP 客户端"""
        if self._instance:
            await self._instance.close_aiohttp_client()

    def _sync_cleanup(self) -> None:
        """同步清理 HTTP 客户端"""
        pass


async def get_http_client() -> AsyncHttpClient:
    """获取 HTTP 客户端实例"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(HttpClientManager.name)
    except KeyError:
        logger.warning(f"HttpClientManager not found in context, registering new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(HttpClientManager())
            return await app_context.async_get_instance(HttpClientManager.name)
        except Exception as e:
            logger.error(f"Failed to register HttpClientManager: {e}")
            raise

import logging
from typing import Optional, Union, Dict

from bisheng.core.context import BaseContextManager
from bisheng.core.cache.redis_conn import RedisClient

logger = logging.getLogger(__name__)


class RedisManager(BaseContextManager[RedisClient]):
    """Redis 全局管理器

    负责管理 Redis 连接的全局生命周期，提供统一的访问接口
    支持连接池监控、健康检查和便捷的操作管理
    """

    name: str = "redis"

    def __init__(
            self,
            redis_url: Optional[Union[str, Dict]] = None,
            **kwargs
    ):
        super().__init__(self.name, **kwargs)
        self.redis_url = redis_url
        if not self.redis_url:
            raise ValueError("Redis URL is required. Please provide via parameter.")

    async def _async_initialize(self) -> RedisClient:
        """初始化 Redis 连接管理器"""
        return RedisClient(self.redis_url)

    def _sync_initialize(self) -> RedisClient:
        """同步初始化"""
        return RedisClient(self.redis_url)

    async def _sync_cleanup(self) -> None:
        """同步清理 Redis 资源"""
        if self._instance:
            await self._instance.close()

    async def _async_cleanup(self) -> None:
        """清理 Redis 资源"""
        if self._instance:
            await self._instance.close()


async def get_redis_client() -> RedisClient:
    """获取 Redis 客户端实例"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(RedisManager.name)
    except KeyError:
        logger.warning(f"RedisManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(RedisManager(
                redis_url=settings.redis_url
            ))
            return await app_context.async_get_instance(RedisManager.name)
        except Exception as e:
            logger.error(f"Failed to register RedisManager: {e}")
            raise


def get_redis_client_sync() -> RedisClient:
    """同步获取 Redis 客户端实例"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(RedisManager.name)
    except KeyError:
        logger.warning(f"RedisManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(RedisManager(
                redis_url=settings.redis_url
            ))
            return app_context.sync_get_instance(RedisManager.name)
        except Exception as e:
            logger.error(f"Failed to register RedisManager: {e}")
            raise

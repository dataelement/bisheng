import logging
from typing import Optional, Union, Dict

from bisheng.core.context import BaseContextManager
from bisheng.core.cache.redis_conn import RedisClient

logger = logging.getLogger(__name__)


class RedisManager(BaseContextManager[RedisClient]):
    """Redis Global Manager

    Responsible for management Redis Global lifecycle of connectivity, providing a unified access interface
    Supports connection pool monitoring, health checks, and easy operations management
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
        """Inisialisasi Redis Connection Manager"""
        return RedisClient(self.redis_url)

    def _sync_initialize(self) -> RedisClient:
        """Synchronization Initialization"""
        return RedisClient(self.redis_url)

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Redis reasourse"""
        if self._instance:
            self._instance.close()

    async def _async_cleanup(self) -> None:
        """Cleaned Redis reasourse"""
        if self._instance:
            await self._instance.aclose()


async def get_redis_client() -> RedisClient:
    """Dapatkan Redis Client Instance"""
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
    """Synchronous fetch Redis Client Instance"""
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

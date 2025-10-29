import logging
from abc import ABC
from typing import Union

from bisheng.core.config.settings import MinioConf
from bisheng.core.context import BaseContextManager
from bisheng.core.storage.minio.minio_storage import MinioStorage

logger = logging.getLogger(__name__)


class MinioManager(BaseContextManager[MinioStorage], ABC):
    """Minio 全局管理器

    负责管理 Minio 存储的全局生命周期，提供统一的访问接口
    支持连接池监控、健康检查和便捷的存储管理
    """

    name: str = "minio"

    def __init__(
            self,
            minio_config: Union[MinioConf, dict],
            **kwargs
    ):
        super().__init__(self.name, **kwargs)
        self.minio_config = minio_config
        if isinstance(self.minio_config, dict):
            self.minio_config = MinioConf(**self.minio_config)

    async def _async_initialize(self) -> MinioStorage:
        """初始化 Minio 存储管理器"""
        return MinioStorage(
            self.minio_config
        )

    def _sync_initialize(self) -> MinioStorage:
        """同步初始化"""
        return MinioStorage(
            self.minio_config
        )

    def _sync_cleanup(self) -> None:
        """同步清理 Minio 资源"""
        if self._instance:
            self._instance.close_sync()

    async def _async_cleanup(self) -> None:
        """清理 Minio 资源"""
        if self._instance:
            await self._instance.close()


async def get_minio_storage() -> MinioStorage:
    """获取 Minio 存储实例"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(MinioManager.name)
    except KeyError:
        logger.warning(f"MinioManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(MinioManager(
                minio_config=settings.minio
            ))
            return await app_context.async_get_instance(MinioManager.name)
        except Exception as e:
            logger.error(f"Failed to register MinioManager: {e}")
            raise


def get_minio_storage_sync() -> MinioStorage:
    """同步获取 Minio 存储实例"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(MinioManager.name)
    except KeyError:
        logger.warning(f"MinioManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(MinioManager(
                minio_config=settings.minio
            ))
            return app_context.sync_get_instance(MinioManager.name)
        except Exception as e:
            logger.error(f"Failed to register MinioManager: {e}")
            raise

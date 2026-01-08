import logging
from abc import ABC
from typing import Union

from bisheng.core.config.settings import MinioConf
from bisheng.core.context import BaseContextManager
from bisheng.core.storage.minio.minio_storage import MinioStorage

logger = logging.getLogger(__name__)


class MinioManager(BaseContextManager[MinioStorage]):
    """Minio Global Manager

    Responsible for management Minio Global lifecycle of storage, providing a unified access interface
    Supports connection pool monitoring, health checks, and easy storage management
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
        """Inisialisasi Minio Storage Manager"""
        return MinioStorage(
            self.minio_config
        )

    def _sync_initialize(self) -> MinioStorage:
        """Synchronization Initialization"""
        return MinioStorage(
            self.minio_config
        )

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Minio reasourse"""
        if self._instance:
            self._instance.close_sync()

    async def _async_cleanup(self) -> None:
        """Cleaned Minio reasourse"""
        if self._instance:
            await self._instance.close()


async def get_minio_storage() -> MinioStorage:
    """Dapatkan Minio Storage Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(MinioManager.name)
    except KeyError:
        logger.warning(f"MinioManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(MinioManager(
                minio_config=settings.object_storage.minio
            ))
            return await app_context.async_get_instance(MinioManager.name)
        except Exception as e:
            logger.error(f"Failed to register MinioManager: {e}")
            raise


def get_minio_storage_sync() -> MinioStorage:
    """Synchronous fetch Minio Storage Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(MinioManager.name)
    except KeyError:
        logger.warning(f"MinioManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(MinioManager(
                minio_config=settings.object_storage.minio
            ))
            return app_context.sync_get_instance(MinioManager.name)
        except Exception as e:
            logger.error(f"Failed to register MinioManager: {e}")
            raise

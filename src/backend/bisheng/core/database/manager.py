"""数据库全局管理器

提供数据库上下文的全局管理和便捷访问方法
支持健康检查、连接池监控和事务管理
"""
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context import BaseContextManager
from bisheng.core.database import DatabaseConnectionManager

logger = logging.getLogger(__name__)


class DatabaseManager(BaseContextManager[DatabaseConnectionManager]):
    """数据库全局管理器

    负责管理数据库连接的全局生命周期，提供统一的访问接口
    支持连接池监控、健康检查和便捷的会话管理
    """

    name: str = "database"

    def __init__(
            self,
            database_url: Optional[str] = None,
            engine_config: Optional[Dict[str, Any]] = None,
            **kwargs
    ):
        super().__init__(self.name, **kwargs)
        self.database_url = database_url
        if not self.database_url:
            raise ValueError("Database URL is required. Please provide via parameter or settings.database_url")
        self.engine_config = engine_config or {}

    async def _async_initialize(self) -> DatabaseConnectionManager:
        """初始化数据库连接管理器"""
        return DatabaseConnectionManager(
            self.database_url,
            **self.engine_config
        )

    def _sync_initialize(self) -> DatabaseConnectionManager:
        """同步初始化"""
        return DatabaseConnectionManager(
            self.database_url,
            **self.engine_config
        )

    async def _async_cleanup(self) -> None:
        """清理数据库资源"""
        if self._instance:
            await self._instance.close()

    def _sync_cleanup(self) -> None:
        """同步清理数据库资源"""
        if self._instance:
            self._instance.close_sync()

    async def health_check(self) -> bool:
        """数据库健康检查

        Returns:
            bool: True 如果数据库连接正常，False 否则
        """
        try:
            database_instance = await self.async_get_instance()

            # 使用异步会话执行简单查询
            async with database_instance.async_session() as session:
                await session.exec(text("SELECT 1"))

            logger.debug("Database health check passed")
            return True

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def create_tables_if_not_exists(self) -> None:
        """创建数据库表（如果不存在）

        这是一个便捷方法，用于初始化数据库结构
        """
        try:
            database_instance = await self.async_get_instance()
            await database_instance.create_db_and_tables()
            logger.info("Database tables created or verified successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise


async def get_database_connection() -> DatabaseConnectionManager:
    """获取全局数据库连接管理器实例

    Returns:
        DatabaseConnectionManager: 数据库连接管理器实例

    Raises:
        ContextError: 如果数据库上下文未注册或初始化失败
    """
    from bisheng.core.context.manager import app_context
    try:
        return await app_context.async_get_instance(DatabaseManager.name)
    except KeyError:
        logger.warning(f"Database context not found, registering default instance")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(DatabaseManager(settings.database_url))
            return await app_context.async_get_instance(DatabaseManager.name)
        except Exception as e:
            logger.error(f"Failed to register and initialize database context: {e}")
            raise


def sync_get_database_connection() -> DatabaseConnectionManager:
    """同步获取全局数据库连接管理器实例

    Returns:
        DatabaseConnectionManager: 数据库连接管理器实例

    Raises:
        ContextError: 如果数据库上下文未注册或初始化失败
    """
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(DatabaseManager.name)
    except KeyError:
        logger.warning(f"Database context not found, registering default instance")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(DatabaseManager(settings.database_url))
            return app_context.sync_get_instance(DatabaseManager.name)
        except Exception as e:
            logger.error(f"Failed to register and initialize database context: {e}")
            raise


@asynccontextmanager
async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话的便捷方法

    Example:
        async with get_async_db_session() as session:
            result = await session.execute("SELECT * FROM users")

    Yields:
        AsyncSession: 异步数据库会话
    """
    db_manager = await get_database_connection()
    async with db_manager.async_session() as session:
        yield session


@contextmanager
def get_sync_db_session():
    """获取同步数据库会话的便捷方法

    Example:
        with get_sync_db_session() as session:
            result = session.execute("SELECT * FROM users")

    Yields:
        Session: 同步数据库会话
    """
    db_manager = sync_get_database_connection()
    with db_manager.create_session() as session:
        yield session

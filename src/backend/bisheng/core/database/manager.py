"""Database Global Manager

Provides global management and easy access to database context
Supports health checks, connection pool monitoring, and transaction management
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
    """Database Global Manager

    Responsible for managing the global lifecycle of database connections and providing a unified access interface
    Supports connection pool monitoring, health checks, and easy session management
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
        """Initialize Database Connection Manager"""
        return DatabaseConnectionManager(
            self.database_url,
            **self.engine_config
        )

    def _sync_initialize(self) -> DatabaseConnectionManager:
        """Synchronization Initialization"""
        return DatabaseConnectionManager(
            self.database_url,
            **self.engine_config
        )

    async def _async_cleanup(self) -> None:
        """Clean up database resources"""
        if self._instance:
            await self._instance.close()

    def _sync_cleanup(self) -> None:
        """Synchronously clean up database resources"""
        if self._instance:
            self._instance.close_sync()

    async def health_check(self) -> bool:
        """Database Health Check

        Returns:
            bool: True If the database connection is normal,False Otherwise, 
        """
        try:
            database_instance = await self.async_get_instance()

            # Perform simple queries using asynchronous sessions
            async with database_instance.async_session() as session:
                await session.exec(text("SELECT 1"))

            logger.debug("Database health check passed")
            return True

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def create_tables_if_not_exists(self) -> None:
        """Create a database table (if it does not exist)

        This is a convenient method for initializing the database structure
        """
        try:
            database_instance = await self.async_get_instance()
            await database_instance.create_db_and_tables()
            logger.info("Database tables created or verified successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise


async def get_database_connection() -> DatabaseConnectionManager:
    """Get Global Database Connection Manager Instance

    Returns:
        DatabaseConnectionManager: Database Connection Manager Instance

    Raises:
        ContextError: If the database context is not registered or initialization fails
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
    """Get global database connection manager instance synchronously

    Returns:
        DatabaseConnectionManager: Database Connection Manager Instance

    Raises:
        ContextError: If the database context is not registered or initialization fails
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
    """A convenient way to get asynchronous database sessions

    Example:
        async with get_async_db_session() as session:
            result = await session.execute("SELECT * FROM users")

    Yields:
        AsyncSession: Asynchronous database session
    """
    db_manager = await get_database_connection()
    async with db_manager.async_session() as session:
        yield session


@contextmanager
def get_sync_db_session():
    """Convenient way to get synchronized database sessions

    Example:
        with get_sync_db_session() as session:
            result = session.execute("SELECT * FROM users")

    Yields:
        Session: Synchronize database sessions
    """
    db_manager = sync_get_database_connection()
    with db_manager.create_session() as session:
        yield session

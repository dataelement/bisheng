"""数据库连接管理模块"""
import logging
from typing import Optional, Dict, Any, Generator
from contextlib import asynccontextmanager, contextmanager
from sqlalchemy import create_engine, Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """数据库连接管理器

    负责管理数据库引擎的创建、连接池配置和生命周期管理
    """

    def __init__(self, database_url: str, **engine_kwargs):
        self.database_url = database_url
        print(f'同步数据库连接URL：{database_url}')
        self.async_database_url = database_url.replace("dmPython", "dmAsync")
        print(f'异步数据库连接URL：{self.async_database_url}')
        self.engine_kwargs = engine_kwargs
        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._async_session_maker: Optional[async_sessionmaker] = None

    def _get_default_engine_config(self) -> Dict[str, Any]:
        config = {
            'pool_size': 100,
            'max_overflow': 20,
            'pool_timeout': 3,  # 修改点：从30秒调整为3秒，适配达梦数据库超时特性
            'pool_pre_ping': True,
            'pool_recycle': 3600,  # 1 hour
        }
        return config
    @property
    def engine(self) -> Engine:
        """获取同步数据库引擎"""
        if self._engine is None:
            config = self._get_default_engine_config()
            # config.update(self.engine_kwargs)

            self._engine = create_engine(
                self.database_url,
                **config
            )
            logger.debug(f"Created sync database engine for {self.database_url}")

        return self._engine

    @property
    def async_engine(self) -> AsyncEngine:
        """获取异步数据库引擎
        """
        if self._async_engine is None:
            self._async_engine = create_async_engine(self.async_database_url, echo=True)
            logger.debug(f"Created async database engine for {self.async_database_url}")
        return self._async_engine

    @contextmanager
    def create_session(self) -> Generator[Session, Any, None]:
        """创建同步会话"""
        session_maker = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=True,
            autocommit=False
        )

        with session_maker() as session:
            try:
                yield session
            except Exception as e:
                session.rollback()
                logger.error(f"Database session rolled back due to error: {e}")
                raise
            finally:
                session.close()

    @asynccontextmanager
    async def async_session(self):
        """异步会话上下文管理器"""

        session_maker = async_sessionmaker(
            bind=self.async_engine,
            expire_on_commit=False
        )

        async with session_maker() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logger.error(f"Database session rolled back due to error: {e}")
                raise
            finally:
                await session.close()

    async def create_db_and_tables(self) -> None:
        """创建数据库和表
        修改点4：完善异常日志，增加调试信息（同参考代码风格）
        """

        logger.debug("Creating database and tables (async)")  # 新增：调试日志
        async with self.async_engine.begin() as conn:
            try:
                await conn.run_sync(SQLModel.metadata.create_all)
                logger.debug("Tables created successfully***********************")  # 新增：创建成功调试日志
            except OperationalError as oe:
                logger.warning(f"Table creation skipped due to OperationalError: {oe}")
            except Exception as exc:
                logger.error(f"Error creating tables: {exc}")
                raise RuntimeError("Error creating tables") from exc

        logger.info('Database and tables created successfully')

    # 修改点5：新增删除数据库表的方法（同参考代码）
    async def delete_db_and_tables(self) -> None:
        """删除数据库和表"""
        logger.debug("Deleting database and tables (async)")
        try:
            async with self.async_engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
            logger.debug("Tables deleted successfully")
        except OperationalError as oe:
            logger.warning(f"Table deletion skipped due to OperationalError: {oe}")
        except Exception as exc:
            logger.error(f"Error deleting tables: {exc}")
            raise RuntimeError("Error deleting tables") from exc

        logger.info('Database and tables deleted successfully')

    async def close(self):
        """关闭数据库连接"""
        if self._async_engine:
            await self._async_engine.dispose()
            logger.debug("Async database engine disposed")

    def close_sync(self):
        """同步关闭数据库连接"""
        if self._engine:
            self._engine.dispose()
            logger.debug("Sync database engine disposed")

    def __del__(self):
        """析构函数确保资源释放"""
        if self._engine:
            try:
                self._engine.dispose()
            except Exception:
                pass
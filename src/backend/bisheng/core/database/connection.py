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
        self.async_database_url = self._convert_to_async_url(database_url)
        self.engine_kwargs = engine_kwargs

        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._async_session_maker: Optional[async_sessionmaker] = None

    def _convert_to_async_url(self, url: str) -> str:
        """将同步数据库URL转换为异步URL"""
        if "pymysql" in url:
            return url.replace("pymysql", "aiomysql")
        elif "psycopg2" in url:
            return url.replace("psycopg2", "asyncpg")
        return url

    def _get_default_engine_config(self) -> Dict[str, Any]:
        """获取默认的引擎配置"""
        config = {
            'pool_size': 100,
            'max_overflow': 20,
            'pool_timeout': 30,
            'pool_pre_ping': True,
            'pool_recycle': 3600,  # 1 hour
        }

        # SQLite特殊配置
        if self.database_url.startswith("sqlite"):
            config.update({
                'connect_args': {'check_same_thread': False},
                'poolclass': StaticPool,
                'pool_size': 1,
                'max_overflow': 0,
            })
        # MySQL特殊配置
        elif "mysql" in self.database_url:
            if 'connect_args' not in config:
                config['connect_args'] = {}
            config['connect_args']['charset'] = 'utf8mb4'

        return config

    @property
    def engine(self) -> Engine:
        """获取同步数据库引擎"""
        if self._engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            self._engine = create_engine(
                self.database_url,
                **config
            )
            logger.debug(f"Created sync database engine for {self.database_url}")

        return self._engine

    @property
    def async_engine(self) -> AsyncEngine:
        """获取异步数据库引擎"""
        if self._async_engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            # 移除同步引擎特有的配置
            config.pop('poolclass', None)

            self._async_engine = create_async_engine(
                self.async_database_url,
                **config
            )
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
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
            autocommit=False
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
        """创建数据库和表"""

        async with self.async_engine.begin() as conn:
            try:
                await conn.run_sync(SQLModel.metadata.create_all)
            except OperationalError as oe:
                logger.warning(f"Table creation skipped due to OperationalError: {oe}")
            except Exception as exc:
                logger.error(f"Error creating tables: {exc}")
                raise RuntimeError("Error creating tables") from exc

        logger.info('Database and tables created successfully')

    async def close(self):
        """关闭数据库连接"""
        if self._async_engine:
            await self._async_engine.dispose()
            logger.debug("Async database engine disposed")

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

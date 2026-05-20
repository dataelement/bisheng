"""Database Connection Management Module"""
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Optional, Dict, Any, Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


def _patch_aiomysql_pre_ping() -> None:
    """修正 SQLAlchemy aiomysql pre-ping 的 ping 参数调用。"""
    try:
        from sqlalchemy.dialects.mysql.aiomysql import MySQLDialect_aiomysql
    except ImportError:
        return

    if getattr(MySQLDialect_aiomysql, '_bisheng_pre_ping_patched', False):
        return

    def do_ping(self, dbapi_connection):
        # aiomysql 的 SQLAlchemy 适配层要求显式传入 reconnect 参数。
        dbapi_connection.ping(False)
        return True

    MySQLDialect_aiomysql.do_ping = do_ping
    MySQLDialect_aiomysql._bisheng_pre_ping_patched = True


class DatabaseConnectionManager:
    """Database Connection Manager

    Responsible for managing database engine creation, connection pool configuration and lifecycle management
    """

    def __init__(self, database_url: str, **engine_kwargs):
        self.database_url = database_url
        self.async_database_url = self._convert_to_async_url(database_url)
        self.engine_kwargs = engine_kwargs

        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._async_session_maker: Optional[async_sessionmaker] = None

    def _convert_to_async_url(self, url: str) -> str:
        """Database will be synchronizedURLConvert to AsynchronousURL"""
        if "pymysql" in url:
            return url.replace("pymysql", "aiomysql")
        elif "psycopg2" in url:
            return url.replace("psycopg2", "asyncpg")
        elif "dmPython" in url:
            return url.replace("dmPython", "dmAsync")
        return url

    def _get_default_engine_config(self) -> Dict[str, Any]:
        """Get default engine configuration"""
        config = {
            'pool_size': 100,
            'max_overflow': 20,
            'pool_timeout': 30,
            'pool_pre_ping': True,
            'pool_recycle': 3600,  # 1 hour
        }

        # SQLiteSPECIAL CONFIGURATION
        if self.database_url.startswith("sqlite"):
            config.update({
                'connect_args': {'check_same_thread': False},
                'poolclass': StaticPool,
                'pool_size': 1,
                'max_overflow': 0,
            })
        # MySQLSPECIAL CONFIGURATION
        elif "mysql" in self.database_url:
            if 'connect_args' not in config:
                config['connect_args'] = {}
            config['connect_args']['charset'] = 'utf8mb4'

        return config

    @staticmethod
    def _dm_sync_url(url: str) -> str:
        """Strip the schema/path from a DaMeng sync URL.

        dmPython.connect() takes (user, password, "host:port") and does NOT
        accept a 'database' keyword argument.  The dmSQLAlchemy sync dialect
        maps the URL path component to that keyword, causing a connection error.
        Dropping the path lets the dialect build the correct DSN.

        The dmAsync dialect handles the path correctly, so async URLs are left
        unchanged.

        Note: urlparse lowercases the scheme, so we strip the path manually
        using string operations to preserve the original case (dm+dmPython).
        """
        # Find the path by locating the host:port section and stripping what follows
        # URL format: dm+dmPython://user:pass@host:port/schema?query
        # We want:    dm+dmPython://user:pass@host:port
        at_idx = url.find("@")
        if at_idx == -1:
            return url
        after_at = url[at_idx + 1:]  # host:port/schema?query
        slash_idx = after_at.find("/")
        if slash_idx == -1:
            return url  # no path — nothing to strip
        return url[:at_idx + 1 + slash_idx]  # trim /schema and beyond

    @property
    def engine(self) -> Engine:
        """Get Synchronization Database Engine"""
        if self._engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            sync_url = self.database_url
            if "dm+dmPython" in sync_url:
                sync_url = self._dm_sync_url(sync_url)

            self._engine = create_engine(
                sync_url,
                **config
            )
            logger.debug(f"Created sync database engine for {sync_url}")

        return self._engine

    @property
    def async_engine(self) -> AsyncEngine:
        """Get Asynchronous Database Engine"""
        if self._async_engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            # Remove Synchronization Engine Specific Configuration
            config.pop('poolclass', None)

            if 'mysql+aiomysql' in self.async_database_url:
                _patch_aiomysql_pre_ping()

            self._async_engine = create_async_engine(
                self.async_database_url,
                **config
            )
            logger.debug(f"Created async database engine for {self.async_database_url}")

        return self._async_engine

    @contextmanager
    def create_session(self) -> Generator[Session, Any, None]:
        """Create a sync session"""
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
        """Asynchronous Session Context Manager"""

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
        """Creation of databases and tables"""

        async with self.async_engine.begin() as conn:
            try:
                await conn.run_sync(SQLModel.metadata.create_all)
            except OperationalError as oe:
                # Log full OperationalError so silent failures are visible
                logger.error(f"Table creation OperationalError (tables may be missing): {oe}")
            except Exception as exc:
                logger.error(f"Error creating tables: {exc}")
                raise RuntimeError("Error creating tables") from exc

        # DaMeng: ensure triggers exist for columns that MySQL handles natively
        # but DaMeng requires explicit triggers for.
        if self.async_engine.dialect.name == 'dm':
            self._ensure_dm_triggers()
            self._ensure_dm_computed_triggers()

        logger.info('Database and tables created successfully')

    @staticmethod
    def _dm_quote_table(actual_name: str) -> str:
        """Return the DDL identifier for a DaMeng table name.

        DaMeng stores unquoted identifiers as UPPERCASE.
        Tables whose names contain lowercase letters were created with double
        quotes (e.g. reserved words like `group`, `user`) and must be quoted
        in DDL to preserve their case.  All-uppercase names can be used
        unquoted.
        """
        if actual_name == actual_name.upper():
            return actual_name  # e.g. ROLE, TENANT — no quotes needed
        return f'"{actual_name}"'  # e.g. "group", "user" — reserved word

    def _ensure_dm_triggers(self) -> None:
        """Create or replace BEFORE UPDATE triggers for update_time on DaMeng.

        Uses SYS.ALL_TABLES to get the actual stored table names (UPPERCASE for
        normal tables, lowercase for reserved-word tables created with quotes).
        This avoids the case-mismatch that occurs when using Inspector's
        get_table_names() which always returns lowercase names.
        """
        from sqlalchemy import inspect as sa_inspect, text

        with self.engine.connect() as conn:
            # Get actual stored table names from DaMeng system catalog
            result = conn.execute(text(
                "SELECT TABLE_NAME FROM SYS.ALL_TABLES WHERE OWNER = USER ORDER BY TABLE_NAME"
            ))
            actual_tables = [row[0] for row in result]

            insp = sa_inspect(conn)
            for actual_name in actual_tables:
                try:
                    # Inspector returns columns for lowercase name
                    col_names = [c['name'].lower() for c in insp.get_columns(actual_name.lower())]
                except Exception:
                    try:
                        col_names = [c['name'].lower() for c in insp.get_columns(actual_name)]
                    except Exception:
                        continue

                if 'update_time' not in col_names:
                    continue

                table_ref = self._dm_quote_table(actual_name)
                trigger_name = f'trg_{actual_name.lower()}_update_time'
                trigger_ddl = (
                    f'CREATE OR REPLACE TRIGGER {trigger_name} '
                    f'BEFORE UPDATE ON {table_ref} '
                    f'FOR EACH ROW '
                    f'BEGIN '
                    f'  :new.update_time := CURRENT_TIMESTAMP; '
                    f'END'
                )
                try:
                    conn.exec_driver_sql(trigger_ddl)
                except Exception as exc:
                    logger.warning(f'[dm] Could not create trigger {trigger_name}: {exc}')

    def _ensure_dm_computed_triggers(self) -> None:
        """Create BEFORE INSERT OR UPDATE triggers for Computed columns on DaMeng.

        MySQL supports GENERATED ALWAYS AS (expr) STORED natively.
        DaMeng rejects virtual columns in UNIQUE constraints, so we suppress
        the GENERATED clause at DDL time (@compiles(Computed, 'dm')) and
        instead maintain the value via triggers created here.
        """
        import re
        from sqlmodel import SQLModel

        with self.engine.connect() as conn:
            for tbl in SQLModel.metadata.tables.values():
                computed_cols = [c for c in tbl.columns if c.computed is not None]
                if not computed_cols:
                    continue

                col_names = [c.name for c in tbl.columns]

                for col in computed_cols:
                    # Translate expression: col_name → :new.col_name
                    expr = str(col.computed.sqltext)
                    trigger_expr = expr
                    for name in sorted(col_names, key=len, reverse=True):
                        trigger_expr = re.sub(
                            r'\b' + re.escape(name) + r'\b',
                            f':new.{name}',
                            trigger_expr,
                        )

                    # Use system catalog name for correct DaMeng identifier case
                    table_ref = self._dm_quote_table(tbl.name.upper())
                    trigger_name = f'trg_{tbl.name}_{col.name}'
                    trigger_ddl = (
                        f'CREATE OR REPLACE TRIGGER {trigger_name} '
                        f'BEFORE INSERT OR UPDATE ON {table_ref} '
                        f'FOR EACH ROW '
                        f'BEGIN '
                        f'  :new.{col.name} := {trigger_expr}; '
                        f'END'
                    )
                    try:
                        conn.exec_driver_sql(trigger_ddl)
                        logger.debug(f'[dm] Created computed trigger {trigger_name}')
                    except Exception as exc:
                        logger.warning(
                            f'[dm] Could not create computed trigger {trigger_name}: {exc}'
                        )

    async def close(self):
        """Close database connection"""
        if self._async_engine:
            await self._async_engine.dispose()
            logger.debug("Async database engine disposed")

    def close_sync(self):
        """Synchronously close database connections"""
        if self._engine:
            self._engine.dispose()
            logger.debug("Sync database engine disposed")

    def __del__(self):
        """Destructor ensures release of resources"""
        if self._engine:
            try:
                self._engine.dispose()
            except Exception:
                pass

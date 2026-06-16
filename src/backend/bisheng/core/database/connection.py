"""Database Connection Management Module"""

import logging
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """Database Connection Manager

    Responsible for managing database engine creation, connection pool configuration and lifecycle management
    """

    def __init__(self, database_url: str, **engine_kwargs):
        if "dm+dmPython" in database_url:
            database_url = self._normalize_dm_url(database_url)
        self.database_url = database_url
        self.async_database_url = self._convert_to_async_url(database_url)
        self.engine_kwargs = engine_kwargs

        self._engine: Engine | None = None
        self._async_engine: AsyncEngine | None = None
        self._async_session_maker: async_sessionmaker | None = None

    def _convert_to_async_url(self, url: str) -> str:
        """Database will be synchronizedURLConvert to AsynchronousURL"""
        if "pymysql" in url:
            return url.replace("pymysql", "aiomysql")
        elif "psycopg2" in url:
            return url.replace("psycopg2", "asyncpg")
        elif "dmPython" in url:
            return url.replace("dmPython", "dmAsync")
        return url

    def _get_default_engine_config(self) -> dict[str, Any]:
        """Get default engine configuration"""
        config = {
            "pool_size": 100,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_pre_ping": True,
            "pool_recycle": 3600,  # 1 hour
        }

        # SQLiteSPECIAL CONFIGURATION
        if self.database_url.startswith("sqlite"):
            config.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool,
                    "pool_size": 1,
                    "max_overflow": 0,
                }
            )
        # MySQLSPECIAL CONFIGURATION
        elif "mysql" in self.database_url:
            if "connect_args" not in config:
                config["connect_args"] = {}
            config["connect_args"]["charset"] = "utf8mb4"

        return config

    @staticmethod
    def _normalize_dm_url(url: str) -> str:
        """Carry a DaMeng schema via the URL query string, never the path.

        DaMeng selects the active schema through the ``schema`` connect kwarg
        (it defaults to the login user). SQLAlchemy maps a URL *path*
        (``/SCHEMA``) to the ``database`` connect kwarg, which dmPython rejects
        ("'database' is an invalid keyword argument"). dmSQLAlchemy's
        ``create_connect_args`` passes the URL *query string* straight through
        to ``connect()``, and both the sync (dmPython) and async (dmAsync)
        dialects accept ``schema=``.

        So we move any path-specified schema into ``?schema=`` and clear the
        path. The result connects identically for the sync and async dialects,
        which is why both engines can share this single normalized URL. An
        explicit ``?schema=`` already present takes precedence over the path.
        """
        parsed = make_url(url)
        schema = parsed.query.get("schema") or parsed.database
        # set(database=None) is a no-op (None means "keep"); _replace forces it.
        new = parsed._replace(database=None)
        if schema:
            query = {k: v for k, v in new.query.items() if k != "schema"}
            query["schema"] = schema
            new = new.set(query=query)
        return new.render_as_string(hide_password=False)

    @property
    def engine(self) -> Engine:
        """Get Synchronization Database Engine"""
        if self._engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)
            # StaticPool (SQLite) rejects QueuePool sizing kwargs; drop them so
            # an externally-supplied pool config doesn't break SQLite engines.
            if config.get("poolclass") is StaticPool:
                for key in ("pool_size", "max_overflow", "pool_timeout"):
                    config.pop(key, None)

            # DaMeng URLs are already normalized in __init__ (schema moved to
            # the query string), so database_url is used as-is for every engine.
            self._engine = create_engine(self.database_url, **config)
            logger.debug(f"Created sync database engine for {self.database_url}")

        return self._engine

    @property
    def async_engine(self) -> AsyncEngine:
        """Get Asynchronous Database Engine"""
        if self._async_engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            # Remove Synchronization Engine Specific Configuration
            config.pop("poolclass", None)

            self._async_engine = create_async_engine(self.async_database_url, **config)
            logger.debug(f"Created async database engine for {self.async_database_url}")

        return self._async_engine

    @contextmanager
    def create_session(self) -> Generator[Session, Any, None]:
        """Create a sync session"""
        session_maker = sessionmaker(
            bind=self.engine, class_=Session, expire_on_commit=False, autoflush=True, autocommit=False
        )

        with session_maker() as session:
            try:
                yield session
            except BaseException as e:
                # Catch BaseException (not just Exception) so non-Exception
                # interruptions (KeyboardInterrupt, and CancelledError if ever
                # driven from async) still roll back rather than leaving an open
                # transaction holding row locks.
                session.rollback()
                if isinstance(e, Exception):
                    logger.error(f"Database session rolled back due to error: {e}")
                raise
            finally:
                session.close()

    @asynccontextmanager
    async def async_session(self):
        """Asynchronous Session Context Manager"""

        session_maker = async_sessionmaker(
            bind=self.async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=True, autocommit=False
        )

        async with session_maker() as session:
            try:
                yield session
            except BaseException as e:
                # CancelledError is a BaseException (Py3.8+). Catching only
                # Exception let a cancelled request skip rollback, leaving an
                # open transaction that held a row lock (idle-in-transaction)
                # and stalled the whole connection pool. Roll back on ANY
                # exceptional exit, including cancellation.
                await session.rollback()
                if isinstance(e, Exception):
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
        if self.async_engine.dialect.name == "dm":
            self._ensure_dm_triggers()
            self._ensure_dm_computed_triggers()

        logger.info("Database and tables created successfully")

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
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        with self.engine.connect() as conn:
            # Get actual stored table names from DaMeng system catalog
            result = conn.execute(text("SELECT TABLE_NAME FROM SYS.ALL_TABLES WHERE OWNER = USER ORDER BY TABLE_NAME"))
            actual_tables = [row[0] for row in result]

            insp = sa_inspect(conn)
            for actual_name in actual_tables:
                try:
                    # Inspector returns columns for lowercase name
                    col_names = [c["name"].lower() for c in insp.get_columns(actual_name.lower())]
                except Exception:
                    try:
                        col_names = [c["name"].lower() for c in insp.get_columns(actual_name)]
                    except Exception:
                        continue

                if "update_time" not in col_names:
                    continue

                table_ref = self._dm_quote_table(actual_name)
                trigger_name = f"trg_{actual_name.lower()}_update_time"
                trigger_ddl = (
                    f"CREATE OR REPLACE TRIGGER {trigger_name} "
                    f"BEFORE UPDATE ON {table_ref} "
                    f"FOR EACH ROW "
                    f"BEGIN "
                    f"  :new.update_time := CURRENT_TIMESTAMP; "
                    f"END"
                )
                try:
                    conn.exec_driver_sql(trigger_ddl)
                except Exception as exc:
                    logger.warning(f"[dm] Could not create trigger {trigger_name}: {exc}")

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
                            r"\b" + re.escape(name) + r"\b",
                            f":new.{name}",
                            trigger_expr,
                        )

                    # Use system catalog name for correct DaMeng identifier case
                    table_ref = self._dm_quote_table(tbl.name.upper())
                    trigger_name = f"trg_{tbl.name}_{col.name}"
                    trigger_ddl = (
                        f"CREATE OR REPLACE TRIGGER {trigger_name} "
                        f"BEFORE INSERT OR UPDATE ON {table_ref} "
                        f"FOR EACH ROW "
                        f"BEGIN "
                        f"  :new.{col.name} := {trigger_expr}; "
                        f"END"
                    )
                    try:
                        conn.exec_driver_sql(trigger_ddl)
                        logger.debug(f"[dm] Created computed trigger {trigger_name}")
                    except Exception as exc:
                        logger.warning(f"[dm] Could not create computed trigger {trigger_name}: {exc}")

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

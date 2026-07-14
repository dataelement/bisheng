"""Database connection-pool configuration tests."""

from bisheng.core.config.settings import DatabasePoolConf, Settings
from bisheng.core.database.connection import DatabaseConnectionManager
from bisheng.core.database.manager import DatabaseManager


def test_database_pool_defaults_match_existing_engine_defaults():
    conf = DatabasePoolConf()

    assert conf.as_engine_kwargs() == {
        "pool_size": 100,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    }


def test_settings_parses_database_pool_overrides():
    settings = Settings(
        database_pool={
            "pool_size": 30,
            "max_overflow": 10,
            "pool_timeout": 15,
        }
    )

    assert settings.database_pool.pool_size == 30
    assert settings.database_pool.max_overflow == 10
    assert settings.database_pool.pool_timeout == 15
    assert settings.database_pool.pool_recycle == 3600
    assert settings.database_pool.pool_pre_ping is True


def test_database_manager_applies_pool_config_to_engine():
    manager = DatabaseManager(
        "mysql+pymysql://user:password@localhost/bisheng",
        engine_config=DatabasePoolConf(pool_size=7, max_overflow=3).as_engine_kwargs(),
    )

    connection_manager = manager._sync_initialize()

    assert connection_manager.engine.pool.size() == 7
    assert connection_manager.engine.pool._max_overflow == 3
    connection_manager.close_sync()


def test_sqlite_engines_ignore_queue_pool_sizing_options():
    connection_manager = DatabaseConnectionManager(
        "sqlite:///:memory:",
        **DatabasePoolConf(pool_size=7, max_overflow=3).as_engine_kwargs(),
    )

    assert connection_manager.engine is not None
    connection_manager.close_sync()


async def test_async_sqlite_engine_ignores_queue_pool_sizing_options():
    connection_manager = DatabaseConnectionManager(
        "sqlite+aiosqlite:///:memory:",
        **DatabasePoolConf(pool_size=7, max_overflow=3).as_engine_kwargs(),
    )

    assert connection_manager.async_engine is not None
    await connection_manager.close()

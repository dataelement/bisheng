"""Make the DB connection-pool parameters configurable via config.yaml.

Background: pool_size/max_overflow/etc. were hardcoded in
``DatabaseConnectionManager._get_default_engine_config``. On the 109 DaMeng
deployment that 100-per-process pool x 8 uvicorn workers pushed the server
toward its session cap. Ops needs to tune these without editing code, so they
move into ``settings.database_pool`` (config.yaml).
"""

from __future__ import annotations

from bisheng.core.config.settings import DatabasePoolConf, Settings
from bisheng.core.database.manager import DatabaseManager

_MYSQL_URL = "mysql+pymysql://u:p@localhost/db"


def test_database_pool_conf_defaults_match_hardcoded():
    """Defaults must equal the previous hardcoded values (no behaviour change
    when config.yaml omits the section)."""
    conf = DatabasePoolConf()
    assert conf.pool_size == 100
    assert conf.max_overflow == 20
    assert conf.pool_timeout == 30
    assert conf.pool_recycle == 3600
    assert conf.pool_pre_ping is True


def test_settings_parses_database_pool_override():
    settings = Settings(database_pool={"pool_size": 12, "max_overflow": 8})
    assert settings.database_pool.pool_size == 12
    assert settings.database_pool.max_overflow == 8
    # Unspecified keys keep their defaults.
    assert settings.database_pool.pool_timeout == 30


def test_database_manager_applies_pool_config_to_engine():
    manager = DatabaseManager(
        _MYSQL_URL,
        engine_config=DatabasePoolConf(pool_size=7, max_overflow=3).model_dump(),
    )
    conn_manager = manager._sync_initialize()
    assert conn_manager.engine.pool.size() == 7


def test_sqlite_engine_ignores_pool_sizing_kwargs():
    """SQLite uses StaticPool, which rejects QueuePool sizing kwargs. An
    externally-supplied pool config must not break a SQLite engine."""
    from bisheng.core.database.connection import DatabaseConnectionManager

    conn_manager = DatabaseConnectionManager("sqlite:///:memory:", **DatabasePoolConf().model_dump())
    # Must not raise TypeError on engine creation.
    assert conn_manager.engine is not None

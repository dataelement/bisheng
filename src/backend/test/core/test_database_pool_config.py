"""Make the DB connection-pool parameters configurable via config.yaml.

Background: pool_size/max_overflow/etc. were hardcoded in
``DatabaseConnectionManager._get_default_engine_config``. On the 109 DaMeng
deployment that 100-per-process pool x 8 uvicorn workers pushed the server
toward its session cap. Ops needs to tune these without editing code, so they
move into ``settings.database_pool`` (config.yaml).
"""

from __future__ import annotations

import ssl

import pytest

from bisheng.core.config.settings import DatabasePoolConf, Settings
from bisheng.core.database.connection import DatabaseConnectionManager
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
    assert conf.ssl.enabled is False
    assert "connect_args" not in conf.as_engine_kwargs()


def test_settings_parses_database_pool_override():
    settings = Settings(database_pool={"pool_size": 12, "max_overflow": 8})
    assert settings.database_pool.pool_size == 12
    assert settings.database_pool.max_overflow == 8
    # Unspecified keys keep their defaults.
    assert settings.database_pool.pool_timeout == 30


def test_database_pool_builds_ssl_context_when_enabled():
    conf = DatabasePoolConf(ssl={"enabled": True, "verify_hostname": False})

    connect_args = conf.as_engine_kwargs()["connect_args"]

    assert isinstance(connect_args["ssl"], ssl.SSLContext)
    assert connect_args["ssl"].check_hostname is False


def test_database_pool_requires_complete_mutual_tls_certificate_pair():
    with pytest.raises(ValueError, match="cert_file and key_file"):
        DatabasePoolConf(ssl={"enabled": True, "cert_file": "/certs/client.pem"})


def test_database_connection_manager_merges_ssl_and_mysql_charset():
    context = ssl.create_default_context()
    manager = DatabaseConnectionManager(_MYSQL_URL, connect_args={"ssl": context})

    config = manager._get_engine_config()

    assert config["connect_args"] == {"charset": "utf8mb4", "ssl": context}


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
    conn_manager = DatabaseConnectionManager("sqlite:///:memory:", **DatabasePoolConf().model_dump())
    # Must not raise TypeError on engine creation.
    assert conn_manager.engine is not None

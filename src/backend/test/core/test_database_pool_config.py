"""Database connection-pool configuration tests."""

from pathlib import Path

import yaml

from bisheng.core.config.settings import DatabasePoolConf, Settings
from bisheng.core.context.manager import ApplicationContextManager
from bisheng.core.database.connection import DatabaseConnectionManager
from bisheng.core.database.manager import DatabaseManager

SYNC_DEFAULTS = {
    "pool_size": 20,
    "max_overflow": 10,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}
ASYNC_DEFAULTS = {
    "pool_size": 40,
    "max_overflow": 20,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def test_database_pool_defaults_are_independent():
    conf = DatabasePoolConf()
    settings = Settings(database_pool={})

    assert conf.as_sync_engine_kwargs() == SYNC_DEFAULTS
    assert conf.as_async_engine_kwargs() == ASYNC_DEFAULTS
    assert settings.database_pool.as_sync_engine_kwargs() == SYNC_DEFAULTS
    assert settings.database_pool.as_async_engine_kwargs() == ASYNC_DEFAULTS


def test_settings_parses_complete_independent_database_pool_overrides():
    settings = Settings(
        database_pool={
            "sync": {
                "pool_size": 11,
                "max_overflow": 12,
                "pool_timeout": 13,
                "pool_recycle": 14,
                "pool_pre_ping": False,
            },
            "async": {
                "pool_size": 21,
                "max_overflow": 22,
                "pool_timeout": 23,
                "pool_recycle": 24,
                "pool_pre_ping": True,
            },
        }
    )

    assert settings.database_pool.as_sync_engine_kwargs() == {
        "pool_size": 11,
        "max_overflow": 12,
        "pool_timeout": 13,
        "pool_recycle": 14,
        "pool_pre_ping": False,
    }
    assert settings.database_pool.as_async_engine_kwargs() == {
        "pool_size": 21,
        "max_overflow": 22,
        "pool_timeout": 23,
        "pool_recycle": 24,
        "pool_pre_ping": True,
    }


def test_database_pool_allows_sync_only_partial_override():
    conf = DatabasePoolConf.model_validate({"sync": {"pool_size": 8}})

    assert conf.as_sync_engine_kwargs() == {**SYNC_DEFAULTS, "pool_size": 8}
    assert conf.as_async_engine_kwargs() == ASYNC_DEFAULTS


def test_database_pool_allows_async_only_partial_override():
    conf = DatabasePoolConf.model_validate({"async": {"pool_timeout": 9}})

    assert conf.as_sync_engine_kwargs() == SYNC_DEFAULTS
    assert conf.as_async_engine_kwargs() == {**ASYNC_DEFAULTS, "pool_timeout": 9}


def test_legacy_flat_pool_fields_override_both_engines_per_field():
    conf = DatabasePoolConf(pool_size=30, pool_timeout=15)

    assert conf.as_sync_engine_kwargs() == {
        **SYNC_DEFAULTS,
        "pool_size": 30,
        "pool_timeout": 15,
    }
    assert conf.as_async_engine_kwargs() == {
        **ASYNC_DEFAULTS,
        "pool_size": 30,
        "pool_timeout": 15,
    }


def test_engine_specific_fields_override_legacy_flat_fields():
    conf = DatabasePoolConf.model_validate(
        {
            "pool_size": 30,
            "pool_timeout": 15,
            "sync": {"pool_size": 10},
            "async": {"max_overflow": 30},
        }
    )

    assert conf.as_sync_engine_kwargs() == {
        **SYNC_DEFAULTS,
        "pool_size": 10,
        "pool_timeout": 15,
    }
    assert conf.as_async_engine_kwargs() == {
        **ASYNC_DEFAULTS,
        "pool_size": 30,
        "max_overflow": 30,
        "pool_timeout": 15,
    }


def test_complete_legacy_pool_config_keeps_existing_capacity():
    conf = DatabasePoolConf(
        pool_size=100,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
    )

    expected = {
        "pool_size": 100,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    }
    assert conf.as_sync_engine_kwargs() == expected
    assert conf.as_async_engine_kwargs() == expected


def test_application_context_registers_independent_pool_configs(monkeypatch):
    captured = {}

    class CapturingDatabaseManager:
        name = "database"

        def __init__(
            self,
            database_url,
            sync_engine_config,
            async_engine_config,
        ):
            captured["database_url"] = database_url
            captured["sync_engine_config"] = sync_engine_config
            captured["async_engine_config"] = async_engine_config

    monkeypatch.setattr(
        "bisheng.core.database.manager.DatabaseManager",
        CapturingDatabaseManager,
    )
    settings = Settings(
        database_url="sqlite:///:memory:",
        database_pool={
            "sync": {"pool_size": 7, "max_overflow": 3},
            "async": {"pool_size": 17, "max_overflow": 13},
        },
    )

    ApplicationContextManager()._register_default_contexts(settings)

    assert captured == {
        "database_url": "sqlite:///:memory:",
        "sync_engine_config": {**SYNC_DEFAULTS, "pool_size": 7, "max_overflow": 3},
        "async_engine_config": {**ASYNC_DEFAULTS, "pool_size": 17, "max_overflow": 13},
    }


async def test_database_manager_applies_independent_pool_configs_to_engines():
    manager = DatabaseManager(
        "mysql+pymysql://user:password@localhost/bisheng",
        sync_engine_config={**SYNC_DEFAULTS, "pool_size": 7, "max_overflow": 3},
        async_engine_config={**ASYNC_DEFAULTS, "pool_size": 17, "max_overflow": 13},
    )

    connection_manager = manager._sync_initialize()

    assert connection_manager.engine.pool.size() == 7
    assert connection_manager.engine.pool._max_overflow == 3
    assert connection_manager.async_engine.pool.size() == 17
    assert connection_manager.async_engine.pool._max_overflow == 13
    connection_manager.close_sync()
    await connection_manager.close()


def test_sqlite_engines_ignore_queue_pool_sizing_options():
    connection_manager = DatabaseConnectionManager(
        "sqlite:///:memory:",
        sync_engine_config={**SYNC_DEFAULTS, "pool_size": 7, "max_overflow": 3},
        async_engine_config=ASYNC_DEFAULTS,
    )

    assert connection_manager.engine is not None
    connection_manager.close_sync()


async def test_async_sqlite_engine_ignores_queue_pool_sizing_options():
    connection_manager = DatabaseConnectionManager(
        "sqlite+aiosqlite:///:memory:",
        sync_engine_config=SYNC_DEFAULTS,
        async_engine_config={**ASYNC_DEFAULTS, "pool_size": 17, "max_overflow": 13},
    )

    assert connection_manager.async_engine is not None
    await connection_manager.close()


def test_docker_config_declares_independent_pool_defaults():
    config_path = REPOSITORY_ROOT / "docker" / "bisheng" / "config" / "config.yaml"

    class DockerConfigLoader(yaml.SafeLoader):
        pass

    def construct_env_placeholder(loader, node):
        return loader.construct_scalar(node)

    DockerConfigLoader.add_constructor("!env", construct_env_placeholder)
    raw_config = yaml.load(
        config_path.read_text(encoding="utf-8"),
        Loader=DockerConfigLoader,
    )
    config = Settings(database_pool=raw_config["database_pool"])

    assert config.database_pool.as_sync_engine_kwargs() == SYNC_DEFAULTS
    assert config.database_pool.as_async_engine_kwargs() == ASYNC_DEFAULTS

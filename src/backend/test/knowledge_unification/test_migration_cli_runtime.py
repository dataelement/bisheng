"""F118's lazy CLI owns DB/Redis even while ApplicationContext is uninitialized.

ApplicationContext, BaseContextManager, DatabaseManager and SQLite pools are
native. Only Redis transport and the private MinIO opening are substituted;
the global close helper is deliberately left real with its initialized guard.
"""

import asyncio
import importlib
import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text

from bisheng.core.context.base import ContextInitializationError, ContextState
from bisheng.core.context.manager import ApplicationContextManager


@pytest.fixture
def native_runtime(monkeypatch, tmp_path):
    context = importlib.import_module("bisheng.core.context.manager")
    database = importlib.import_module("bisheng.core.database.manager")
    settings_module = importlib.import_module("bisheng.common.services.config_service")
    minio = importlib.import_module("bisheng.knowledge.application.unification_minio")
    # The suite's root import pre-mock replaces redis_manager. Load its real
    # class without changing shared fixtures or using a fake app context.
    path = Path(database.__file__).parents[1] / "cache" / "redis_manager.py"
    spec = importlib.util.spec_from_file_location("f118_cli_native_redis", path)
    redis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redis)
    monkeypatch.setitem(sys.modules, "bisheng.core.cache.redis_manager", redis)
    app = ApplicationContextManager()
    monkeypatch.setattr(context, "app_context", app)
    eager = AsyncMock(side_effect=AssertionError("F118 must not eagerly initialize MinIO or other managers"))
    monkeypatch.setattr(context, "initialize_app_context", eager)
    monkeypatch.setattr(app, "initialize", eager)
    state = SimpleNamespace(app=app, events=[], owned=[], eager=eager, failure=None, transport_closed=False)
    settings = SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        database_pool=SimpleNamespace(as_engine_kwargs=lambda: {}),
        redis_url="redis://unused.invalid:6379/1",
        get_minio_conf=lambda: object(),
    )
    monkeypatch.setattr(settings_module, "settings", settings)
    native_database = database.DatabaseManager

    class OwnedDatabase(native_database):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            state.owned.append(self)

        async def async_close(self):
            state.events.append("database-close")
            await super().async_close()

    class OwnedRedis(redis.RedisManager):
        def __init__(self, **kwargs):
            if state.failure == "constructor":
                raise state.error
            super().__init__(retry_count=1, **kwargs)
            state.owned.append(self)

        async def async_close(self):
            state.events.append("redis-close")
            await super().async_close()

    class RedisTransport:
        def __init__(self, url):
            assert url == settings.redis_url
            if state.failure == "initialize":
                raise state.error

        async def aclose(self):
            state.transport_closed = True

    monkeypatch.setattr(database, "DatabaseManager", OwnedDatabase)
    monkeypatch.setattr(redis, "RedisManager", OwnedRedis)
    monkeypatch.setattr(redis, "RedisClient", RedisTransport)

    @asynccontextmanager
    async def storage(config):
        if state.failure == "storage":
            raise state.error
        try:
            yield SimpleNamespace(
                bucket="f118-public",
                tmp_bucket="f118-private",
                object_exists=lambda *args: None,
                put_object=lambda *args: None,
                get_object=lambda *args: None,
            )
        finally:
            state.events.append("minio-close")

    monkeypatch.setattr(minio.UnificationMinio, "aopen", storage)
    # A real, unrelated registered manager must survive CLI teardown.
    unrelated = native_database(database_url=settings.database_url)
    unrelated.name = "unrelated"
    app.register_context(unrelated)
    state.unrelated = unrelated
    return state


@pytest.mark.parametrize("failure", [None, "body", "cancel", "constructor", "initialize", "storage"])
async def test_lazy_cli_closes_only_owned_managers_on_every_exit(native_runtime, failure):
    state = native_runtime
    state.failure = failure
    state.error = (
        asyncio.CancelledError("original cancellation") if failure == "cancel" else RuntimeError("original failure")
    )
    await state.app.async_get_instance("unrelated")
    connection = None
    disposed = []
    try:
        try:
            async with importlib.import_module("scripts.unify_knowledge_spaces")._runtime(None) as runtime:
                assert not state.app.is_initialized()
                connection = state.owned[0]._instance
                event.listen(
                    connection.async_engine.sync_engine, "engine_disposed", lambda engine: disposed.append(engine)
                )
                async with runtime.sessions() as session:
                    assert (await session.exec(text("SELECT 1"))).scalar_one() == 1
                if failure in {"body", "cancel"}:
                    raise state.error
        except BaseException as error:
            if failure == "initialize":
                assert isinstance(error, ContextInitializationError) and error.__cause__ is state.error
            else:
                assert failure is not None and error is state.error
        else:
            assert failure is None
        assert not state.app.is_initialized()
        state.eager.assert_not_awaited()
        assert all(manager.state is ContextState.CLOSED and manager._instance is None for manager in state.owned)
        expected = ["database-close"] if failure == "constructor" else ["redis-close", "database-close"]
        if failure in {None, "body", "cancel"}:
            expected.insert(0, "minio-close")
            assert len(disposed) == 1
        assert state.events == expected
        assert state.transport_closed is (failure not in {"constructor", "initialize"})
        assert state.unrelated.state is ContextState.READY and state.unrelated._instance is not None
    finally:
        # Release a failing old implementation's SQLite resources as well, so
        # a genuine product red does not leak into the next parametrized case.
        for manager in reversed(state.owned):
            await manager.async_close()
        await state.unrelated.async_close()

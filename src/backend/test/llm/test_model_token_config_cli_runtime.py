"""Native context/pool cleanup at the real CLI's asyncio.run boundary."""

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from bisheng.core.context.base import ContextState
from bisheng.core.context.manager import ApplicationContextManager


@pytest.fixture
async def runtime(monkeypatch, tmp_path):
    context = importlib.import_module("bisheng.core.context.manager")
    database = importlib.import_module("bisheng.core.database.manager")
    config = importlib.import_module("bisheng.common.services.config_service")
    service = importlib.import_module("bisheng.llm.domain.services.model_token_config_upgrade")
    state = SimpleNamespace(
        failure=None,
        owned=[],
        created_loops=[],
        closed_loops=[],
        disposed_loops=[],
        calls=[],
        full_init_calls=0,
    )
    app = ApplicationContextManager()
    monkeypatch.setattr(context, "app_context", app)
    settings = SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        database_pool=SimpleNamespace(as_engine_kwargs=lambda: {}),
    )
    monkeypatch.setattr(config, "settings", settings)
    native_database = database.DatabaseManager
    unrelated = native_database(database_url=settings.database_url)
    unrelated.name = "unrelated"
    app.register_context(unrelated)
    await app.async_get_instance(unrelated.name)

    class OwnedDatabase(native_database):
        def __init__(self, *args, **kwargs):
            if state.failure == "constructor":
                raise RuntimeError("private constructor detail")
            assert kwargs.get("database_url", args[0] if args else None) == settings.database_url
            assert kwargs["engine_config"] == {}
            super().__init__(*args, **kwargs)
            state.owned.append(self)
            state.created_loops.append(asyncio.get_running_loop())

        async def async_close(self):
            state.closed_loops.append(asyncio.get_running_loop())
            assert not asyncio.get_running_loop().is_closed()
            await super().async_close()

    monkeypatch.setattr(database, "DatabaseManager", OwnedDatabase)
    actual_get, actual_register = app.async_get_instance, app.register_context
    observed_engines = set()

    async def get(name):
        connection = await actual_get(name)
        if name == database.DatabaseManager.name:
            engine = connection.async_engine.sync_engine
            if engine not in observed_engines:
                observed_engines.add(engine)
                event.listen(
                    engine, "engine_disposed", lambda engine: state.disposed_loops.append(asyncio.get_running_loop())
                )
            if state.failure == "initialize":
                # Fail after allocating and using a native connection, proving
                # cleanup covers partially successful initialization as well.
                async with connection.async_session() as session:
                    await session.exec(text("SELECT 1"))
                raise RuntimeError("private initialization detail")
        return connection

    def register(manager, *args, **kwargs):
        if manager.name == database.DatabaseManager.name and state.failure == "register":
            raise RuntimeError("private registration detail")
        return actual_register(manager, *args, **kwargs)

    async def forbidden(*args, **kwargs):
        state.full_init_calls += 1
        raise AssertionError("A DB-only preview must not initialize the full API/MinIO environment")

    async def migrate(**kwargs):
        from bisheng.core.database import get_async_db_session

        state.calls.append(kwargs)
        assert not app.is_initialized()
        async with get_async_db_session() as session:
            assert (await session.exec(text("SELECT 1"))).scalar_one() == 1
        if state.failure == "body":
            raise RuntimeError("private migration detail")
        if state.failure == "cancel":
            raise asyncio.CancelledError()
        return {
            "apply": kwargs["apply"],
            "mode": "upgrade",
            "scanned": 1,
            "planned": 0,
            "migrated": 0,
            "errors": [{"reason": "configuration_requires_review"}] if state.failure == "reported_errors" else [],
            "rows": [],
        }

    monkeypatch.setattr(app, "async_get_instance", get)
    monkeypatch.setattr(app, "register_context", register)
    monkeypatch.setattr(app, "initialize", forbidden)
    monkeypatch.setattr(context, "initialize_app_context", forbidden)
    monkeypatch.setattr(service, "migrate_model_token_configs", migrate)
    state.app, state.unrelated = app, unrelated
    try:
        yield state
    finally:
        # Also release resources when running this test against the broken CLI.
        for manager in state.owned:
            await manager.async_close()
        await unrelated.async_close()


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "failure", [None, "reported_errors", "body", "cancel", "constructor", "register", "initialize"]
)
async def test_cli_closes_owned_database_before_loop_exit_on_every_path(
    runtime, monkeypatch, tmp_path, capsys, apply, failure
):
    entry = importlib.import_module("scripts.migrate_model_token_configs")
    runtime.failure = failure
    backup = str(tmp_path / "before.json")
    monkeypatch.setattr(
        sys, "argv", [entry.__file__, "--all-tenants", *(["--apply", "--backup-file", backup] if apply else [])]
    )
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.to_thread(entry.main)
    else:
        result = await asyncio.to_thread(entry.main)
        assert result == (1 if failure == "reported_errors" else 2 if failure else 0)
    output = capsys.readouterr()
    assert "private " not in output.out + output.err
    assert runtime.full_init_calls == 0
    assert not runtime.app.is_initialized()
    assert runtime.unrelated.state is ContextState.READY
    assert all(manager.state is ContextState.CLOSED and manager._instance is None for manager in runtime.owned)
    assert runtime.closed_loops == runtime.created_loops
    assert all(loop.is_closed() for loop in runtime.created_loops)
    assert len(runtime.disposed_loops) == (0 if failure in {"constructor", "register"} else 1)
    assert all(loop in runtime.created_loops for loop in runtime.disposed_loops)
    if failure not in {"constructor", "register", "initialize"}:
        assert runtime.calls == [
            {"apply": apply, "tenant_ids": None, "backup_file": backup if apply else None, "restore_backup": None}
        ]

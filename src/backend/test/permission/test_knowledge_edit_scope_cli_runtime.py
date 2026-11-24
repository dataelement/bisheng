"""CLI ownership at its real asyncio.run boundary, with native DB pools."""

import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text

from bisheng.core.context.manager import ApplicationContextManager
from bisheng.core.openfga.authorization_model_f048 import authorization_model_checksum, build_authorization_model_f048


@pytest.mark.parametrize("command", ["plan", "apply", "verify", "resume"])
@pytest.mark.parametrize("failure", [None, "body", "business", "initialize", "cancel"])
async def test_native_pool_disposed_before_cli_loop_closes(monkeypatch, tmp_path, command, failure):
    entry = importlib.import_module("scripts.upgrade_knowledge_edit_scopes")
    catalog_api = importlib.import_module("bisheng.permission.application.catalog_api")
    upgrade_module = importlib.import_module("bisheng.permission.application.knowledge_edit_scope_upgrade")
    database = importlib.import_module("bisheng.core.database.manager")
    context = importlib.import_module("bisheng.core.context.manager")
    config = importlib.import_module("bisheng.common.services.config_service")
    redis_module = importlib.import_module("bisheng.core.cache.redis_manager")
    fga_module = importlib.import_module("bisheng.core.openfga.client")
    discovery = importlib.import_module("bisheng.core.openfga.discovery")
    app = ApplicationContextManager()
    monkeypatch.setattr(context, "app_context", app)
    settings = SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}",
        database_pool=SimpleNamespace(as_engine_kwargs=lambda: {}),
        redis_url="unused",
        openfga=SimpleNamespace(validate_production_runtime=lambda: None, enabled=True, api_url="unused", timeout=1),
    )
    monkeypatch.setattr(config, "settings", settings)
    loops, disposed, closed, client_closed, redis_closed = [], [], [], [], []
    native = database.DatabaseManager

    class Owned(native):
        def __init__(self, **kwargs):
            assert kwargs["database_url"] == settings.database_url
            super().__init__(**kwargs)
            loops.append(asyncio.get_running_loop())

        async def async_close(self):
            closed.append(asyncio.get_running_loop())
            await super().async_close()

    monkeypatch.setattr(database, "DatabaseManager", Owned)
    original_get = app.async_get_instance

    async def get(name):
        result = await original_get(name)
        if name == Owned.name:
            event.listen(
                result.async_engine.sync_engine,
                "engine_disposed",
                lambda engine: disposed.append(asyncio.get_running_loop()),
            )
            async with result.async_session() as session:
                await session.exec(text("SELECT 1"))
            if failure == "initialize":
                raise RuntimeError("initialization failure after pool allocation")
        return result

    monkeypatch.setattr(app, "async_get_instance", get)
    checksum = authorization_model_checksum(build_authorization_model_f048())
    monkeypatch.setattr(
        catalog_api,
        "SqlCatalogState",
        lambda: SimpleNamespace(
            current_release=AsyncMock(return_value=SimpleNamespace(id=1)),
            authorization_release=AsyncMock(
                return_value=SimpleNamespace(status="ACTIVE", model_checksum=checksum, store_id="s", model_id="m")
            ),
        ),
    )
    monkeypatch.setattr(
        discovery, "discover_openfga_runtime", AsyncMock(return_value=SimpleNamespace(model_checksum=checksum))
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            client_closed.append(asyncio.get_running_loop())

    class Redis:
        name = "test_redis"

        def __init__(self, **kwargs):
            pass

        async def async_close(self):
            redis_closed.append(asyncio.get_running_loop())

    original_register = app.register_context
    monkeypatch.setattr(
        app, "register_context", lambda manager: None if isinstance(manager, Redis) else original_register(manager)
    )

    async def get_with_redis(name):
        return None if name == Redis.name else await get(name)

    monkeypatch.setattr(app, "async_get_instance", get_with_redis)
    monkeypatch.setattr(redis_module, "RedisManager", Redis)
    monkeypatch.setattr(fga_module, "FGAClient", Client)
    monkeypatch.setattr(catalog_api, "OpenFGACatalogProjector", lambda **kwargs: None)

    async def operation(**kwargs):
        if failure == "cancel":
            raise asyncio.CancelledError()
        if failure == "body":
            raise RuntimeError("operation failed")
        if failure == "business":
            from bisheng.common.errcode.permission import PermissionVersionConflictError

            raise PermissionVersionConflictError()
        return {"event": "noop"}

    monkeypatch.setattr(
        upgrade_module,
        "KnowledgeEditScopeUpgrade",
        lambda **kwargs: SimpleNamespace(plan=operation, apply=operation, resume=operation, verify=operation),
    )
    args = [entry.__file__, command]
    if command in {"apply", "resume"}:
        args += ["--operator-id", "7", "--idempotency-key", "runtime-test"]
        args += ["--plan-digest", "digest"] if command == "apply" else ["--draft-id", "2"]
    monkeypatch.setattr(sys, "argv", args)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.to_thread(entry.main)
    else:
        assert await asyncio.to_thread(entry.main) == (2 if failure == "business" else 1 if failure else 0)
    assert loops == closed == disposed
    assert all(loop.is_closed() for loop in loops)
    assert client_closed == ([] if failure == "initialize" else loops)
    assert redis_closed == (loops if command in {"apply", "resume"} and failure != "initialize" else [])

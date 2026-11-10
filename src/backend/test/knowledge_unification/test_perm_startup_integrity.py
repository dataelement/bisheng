"""F118 real lazy startup must not rewrite a published Catalog's scope."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context import ApplicationContextManager
from bisheng.core.openfga.manager import FGAManager
from bisheng.permission.application import catalog_bootstrap, control_state, process_runtime
from bisheng.permission.application.runtime import F048PermissionRuntime, F048RuntimeComponents
from test.knowledge_unification.test_perm_catalog_integrity import canonical_seed
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory


class StartupManager:
    name = "openfga"

    def __init__(self):
        config = SimpleNamespace(dual_model_mode=False, legacy_model_id=None, recent_consistency_window_seconds=5)
        heartbeat = SimpleNamespace(publish=AsyncMock(), remove=AsyncMock())
        self.delegate = FGAManager(config, heartbeat_store=heartbeat)
        self.client = SimpleNamespace(
            store_id="s1", model_id="m1", health=AsyncMock(return_value=True), write_tuples=AsyncMock()
        )
        self.delegate._instance = self.client
        self.delegate._runtime_store_id, self.delegate._runtime_model_id = "s1", "m1"
        self.delegate._runtime_model_checksum = "a" * 64

    async def async_get_instance(self):
        return self.client

    def readiness(self):
        return self.delegate.readiness()

    async def bind_catalog_runtime(self, resolver):
        await self.delegate.bind_catalog_runtime(resolver)

    async def heartbeat(self):
        return await self.delegate.heartbeat()

    async def mark_migration_required(self, **kwargs):
        await self.delegate.mark_migration_required(**kwargs)

    async def async_close(self):
        return None


@pytest.mark.parametrize("kind", ["narrow", "disabled", "fresh"])
async def test_real_lazy_startup_preserves_published_scope_or_seeds_fresh_complete_scope(
    session_factory, monkeypatch, kind
):
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    monkeypatch.setattr(catalog_bootstrap, "get_async_db_session", session_factory)
    state = control_state.SqlPermissionControlState()
    before = None
    if kind != "fresh":
        await canonical_seed(session_factory, narrow=kind == "narrow", disabled=kind == "disabled")
        before = await state.current_catalog()
    context = ApplicationContextManager()
    manager = StartupManager()
    context.register_context(manager)
    context._initialized = True
    monkeypatch.setattr(process_runtime, "app_context", context)

    async def heartbeat_loop(_):
        await asyncio.Event().wait()

    async def initialize(client):
        # This is the real SQL current_catalog path, not a ready Mock.
        await state.current_catalog()
        facade = object.__new__(F048PermissionRuntime)
        facade._client, facade._state = client, state
        return F048RuntimeComponents(facade, state, object(), SimpleNamespace(wait_until_ready=AsyncMock()), object())

    monkeypatch.setattr(process_runtime, "run_f048_process_heartbeat", heartbeat_loop)
    process_runtime.register_f048_permission_runtime_context(initialize)
    try:
        components = await process_runtime.get_f048_process_runtime()
        after = await components.state.current_catalog()
        assert manager.readiness()["ready"]
        if before is not None:
            assert after.checksum == before.checksum
            assert after.action_resource_scopes == before.action_resource_scopes
            manager.client.write_tuples.assert_not_called()
        elif kind == "fresh":
            assert "linsight_skill" in dict(after.action_resource_scopes)["edit"]
            assert not {"use", "use_kb"} & dict(after.action_resource_scopes).keys()
            assert manager.client.write_tuples.await_count > 0
    finally:
        await context.async_close()

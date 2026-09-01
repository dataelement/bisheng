"""F048 API process startup, heartbeat, and shutdown contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng import main
from bisheng.api.services import f048_permission_runtime as api_runtime_module
from bisheng.core.context.manager import ApplicationContextManager
from bisheng.department.domain.services import department_projection_scope
from bisheng.permission.application import process_runtime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class _PermissionFacade:
    async def get_permission_version(self, **kwargs):
        return 1, "permission-context"

    async def mode_for_target(self, target):
        return SimpleNamespace(mode="CUSTOM")


class _ModeState:
    def __init__(self) -> None:
        self.targets = []
        self.mode = SimpleNamespace(mode="INHERIT")

    async def mode_for_target(self, target):
        self.targets.append(target)
        return self.mode


class _LazyManager:
    name = "openfga"

    def __init__(self) -> None:
        self.initializations = 0
        self.bindings = 0
        self.heartbeats = 0

    async def async_get_instance(self):
        self.initializations += 1
        return object()

    def readiness(self):
        return {"migration_required": False, "ready": True}

    async def bind_catalog_runtime(self, resolver):
        del resolver
        self.bindings += 1

    async def heartbeat(self):
        self.heartbeats += 1
        return True

    async def mark_migration_required(self):
        raise AssertionError("migration must not be marked for a valid runtime")

    async def async_close(self):
        return None


def test_api_process_registers_permission_and_department_contexts_lazily(monkeypatch) -> None:
    registered = []
    monkeypatch.setattr(main.settings.openfga, "enabled", True)
    monkeypatch.setattr(
        "bisheng.permission.application.process_runtime.register_f048_permission_runtime_context",
        lambda initializer: registered.append(("permission", initializer)),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.department_projection_scope.register_department_projection_runtime_context",
        lambda: registered.append(("department", None)),
    )

    main._register_permission_runtime_contexts()

    assert [name for name, _ in registered] == ["permission", "department"]
    assert callable(registered[0][1])


@pytest.mark.asyncio
async def test_permission_and_department_contexts_initialize_on_separate_first_access(monkeypatch) -> None:
    context = ApplicationContextManager()
    manager = _LazyManager()
    context.register_context(manager)
    context._initialized = True
    facade = SimpleNamespace(current_catalog=AsyncMock())
    projection = object()
    runtime = SimpleNamespace(
        components=SimpleNamespace(
            facade=facade,
            projection=projection,
        ),
    )
    initialize_calls = 0

    async def initialize(client):
        nonlocal initialize_calls
        assert client is not None
        initialize_calls += 1
        return runtime

    async def heartbeat(bound_manager):
        assert bound_manager is manager
        await asyncio.Event().wait()

    monkeypatch.setattr(process_runtime, "app_context", context)
    monkeypatch.setattr(department_projection_scope, "app_context", context)
    monkeypatch.setattr(process_runtime, "_components", lambda value: value.components)
    monkeypatch.setattr(process_runtime, "run_f048_process_heartbeat", heartbeat)

    process_runtime.register_f048_permission_runtime_context(initialize)
    department_projection_scope.register_department_projection_runtime_context()

    assert initialize_calls == 0
    assert manager.initializations == 0

    assert await process_runtime.get_f048_process_runtime() is runtime
    assert initialize_calls == 1
    assert manager.bindings == 1
    assert manager.heartbeats == 1

    department_runtime = await department_projection_scope.get_department_projection_runtime()
    assert department_runtime._ledger is projection
    assert initialize_calls == 1

    await context.async_close()


def test_health_is_not_coupled_to_f048_migration_state() -> None:
    app = main.create_app()
    health_route = next(route for route in app.routes if getattr(route, "path", None) == "/health")

    assert health_route.endpoint() == {"status": "OK"}
    assert "F048MigrationGateMiddleware" not in {middleware.cls.__name__ for middleware in app.user_middleware}


@pytest.mark.asyncio
async def test_permission_facade_exposes_mode_lookup_to_business_loaders() -> None:
    state = _ModeState()
    runtime = object.__new__(api_runtime_module.F048PermissionRuntime)
    runtime._state = state
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=5,
        resource_type="knowledge_file",
        resource_id="10",
        resource_version=4,
        context_version="permission-context-v4",
        parent_type="knowledge_library",
        parent_id="11",
    )

    mode = await runtime.mode_for_target(target)

    assert mode is state.mode
    assert state.targets == [target]


@pytest.mark.asyncio
async def test_api_runtime_injects_facade_into_business_loaders(
    monkeypatch,
) -> None:
    facade = _PermissionFacade()
    state = object()
    components = SimpleNamespace(
        facade=facade,
        state=state,
        projection=object(),
        marker=object(),
    )

    async def build_runtime(client, *, external_scopes):
        assert external_scopes == {}
        return components

    monkeypatch.setattr(
        api_runtime_module,
        "build_f048_permission_runtime",
        build_runtime,
    )
    for configure_name in (
        "configure_catalog_api",
        "configure_permission_decision_api",
        "configure_resource_permission_api",
        "configure_f048_runtime",
        "configure_linsight_skill_owner_projection",
    ):
        monkeypatch.setattr(
            api_runtime_module,
            configure_name,
            lambda *args, **kwargs: None,
        )

    initialized = await api_runtime_module.initialize_f048_api_runtime(
        SimpleNamespace(store_id="store-live", model_id="model-f048"),
        external_scopes={},
    )

    assert initialized.components is components
    for resource_type in (
        "workflow",
        "assistant",
        "channel",
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "tool",
        "dashboard",
    ):
        loader = initialized.adapters[resource_type]._loader
        assert loader._versions is facade
        assert loader._versions is not state


def test_api_lifespan_does_not_run_f048_data_or_relation_backfill() -> None:
    source = main.lifespan.__wrapped__.__code__
    referenced_names = set(source.co_names)

    assert "migrate_f048_permission_data" not in referenced_names
    assert "relation_model_backfill" not in referenced_names

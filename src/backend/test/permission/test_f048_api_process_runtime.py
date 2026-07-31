"""F048 API process startup, heartbeat, and shutdown contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bisheng import main
from bisheng.api.services import f048_permission_runtime as api_runtime_module
from bisheng.core.context import manager as context_module
from bisheng.permission.application import process_runtime as process_module
from bisheng.permission.domain.schemas import VerifiedPermissionTarget


class _Manager:
    async def async_get_instance(self):
        return object()


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


@pytest.mark.asyncio
async def test_api_process_binds_runtime_before_starting_heartbeat(
    monkeypatch,
) -> None:
    manager = _Manager()
    facade = object()
    projection = object()
    api_runtime = SimpleNamespace(
        components=SimpleNamespace(
            facade=facade,
            projection=projection,
        ),
    )
    calls = []

    async def initialize(client, *, external_scopes):
        calls.append(
            (
                "initialize",
                client,
                external_scopes,
            )
        )
        return api_runtime

    async def bind(bound_manager, runtime):
        calls.append(
            (
                "bind",
                bound_manager,
                runtime,
            )
        )
        return {
            "store_id": "store-live",
            "model_id": "model-f048",
            "catalog_release_id": 12,
        }

    async def heartbeat(bound_manager):
        calls.append(("heartbeat", bound_manager))
        await asyncio.Event().wait()

    monkeypatch.setattr(main.settings.openfga, "enabled", True)
    monkeypatch.setattr(
        context_module.app_context,
        "get_context",
        lambda name: manager,
    )
    monkeypatch.setattr(
        api_runtime_module,
        "initialize_f048_api_runtime",
        initialize,
    )
    monkeypatch.setattr(
        process_module,
        "bind_f048_process_runtime",
        bind,
    )
    monkeypatch.setattr(
        process_module,
        "run_f048_process_heartbeat",
        heartbeat,
    )
    app = SimpleNamespace(state=SimpleNamespace())

    await main._initialize_f048_api_process(app)
    await asyncio.sleep(0)

    assert calls[0][0] == "initialize"
    assert set(calls[0][2]) == {"department"}
    assert calls[1] == ("bind", manager, facade)
    assert calls[2] == ("heartbeat", manager)
    assert app.state.f048_manager is manager
    assert app.state.f048_runtime is api_runtime

    await main._close_f048_api_process(app)
    assert app.state.f048_heartbeat_task.cancelled()


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

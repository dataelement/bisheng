"""F048 API process startup, heartbeat, and shutdown contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bisheng import main
from bisheng.api.services import f048_permission_runtime as api_runtime_module
from bisheng.core.context import manager as context_module
from bisheng.permission.application import process_runtime as process_module


class _Manager:
    async def async_get_instance(self):
        return object()


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

    async def bind(bound_manager, runtime, *, require_config_match):
        calls.append(
            (
                "bind",
                bound_manager,
                runtime,
                require_config_match,
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
    assert calls[1] == ("bind", manager, facade, True)
    assert calls[2] == ("heartbeat", manager)
    assert app.state.f048_manager is manager
    assert app.state.f048_runtime is api_runtime

    await main._close_f048_api_process(app)
    assert app.state.f048_heartbeat_task.cancelled()


def test_api_lifespan_does_not_run_f048_data_or_relation_backfill() -> None:
    source = main.lifespan.__wrapped__.__code__
    referenced_names = set(source.co_names)

    assert "migrate_f048_permission_data" not in referenced_names
    assert "relation_model_backfill" not in referenced_names

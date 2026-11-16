"""F022 backfills existing market items through the system-owned reconciler.

覆盖 AC: AC-04, AC-20.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services import f048_system_resource_bootstrap as bootstrap
from bisheng.api.services.f048_system_resource_bootstrap import SystemOwnedResourceInventory
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedReconcileReport,
    SystemOwnedResourceSpec,
    SystemOwnedResourceState,
)
from scripts import reconcile_f048_system_owned_resources as cli

PLUGIN = SystemOwnedResourceSpec(2, "dsh_market_plugin", "a" * 32, ("visible",), "plugin")
WORKBENCH = SystemOwnedResourceSpec(2, "dsh_market_workbench", "b" * 32, ("visible",), "workbench")
TOOL = SystemOwnedResourceSpec(1, "tool", "902", ("visible",), "preset")


def test_resource_types_default_to_tools_and_accept_market_types():
    assert cli.parse_args([]).resource_types == ["tool"]
    args = cli.parse_args(["--resource-type", "dsh_market_plugin", "--resource-type", "dsh_market_workbench"])
    assert args.resource_types == ["dsh_market_plugin", "dsh_market_workbench"]
    with pytest.raises(SystemExit):
        cli.parse_args(["--resource-type", "workflow"])


@pytest.fixture
def cli_runtime(monkeypatch):
    client = SimpleNamespace(store_id="store", model_id="model")
    components = SimpleNamespace(facade=object(), marker=SimpleNamespace(wait_until_ready=AsyncMock()))
    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(
        cli.app_context, "get_context", lambda name: SimpleNamespace(async_get_instance=AsyncMock(return_value=client))
    )
    monkeypatch.setattr(cli, "build_f048_permission_runtime", AsyncMock(return_value=components))
    tools = AsyncMock(return_value=SystemOwnedResourceInventory((TOOL,), ()))
    market = AsyncMock(return_value=(PLUGIN, WORKBENCH))
    monkeypatch.setattr(cli, "load_system_owned_resource_inventory", tools)
    monkeypatch.setattr(cli, "load_market_system_owned_inventory", market)

    async def reconcile(_facade, resources, *, apply, operator_id):
        before = tuple(
            SystemOwnedResourceState(spec, "CURRENT" if spec is WORKBENCH else "MISSING") for spec in resources
        )
        after = tuple(SystemOwnedResourceState(spec, "CURRENT") for spec in resources) if apply else before
        return SystemOwnedReconcileReport("apply" if apply else "dry-run", before, after)

    reconciled = AsyncMock(side_effect=reconcile)
    monkeypatch.setattr(cli, "reconcile_system_owned_resources", reconciled)
    return SimpleNamespace(tools=tools, market=market, reconcile=reconciled, components=components)


async def test_market_backfill_reconciles_only_the_selected_types(cli_runtime, capsys):
    args = cli.parse_args(
        [
            "--apply",
            "--confirm-store-id",
            "store",
            "--resource-type",
            "dsh_market_plugin",
            "--resource-type",
            "dsh_market_workbench",
        ]
    )
    assert await cli.run(args) == cli.EXIT_OK
    cli_runtime.tools.assert_not_awaited()
    cli_runtime.market.assert_awaited_once_with(("dsh_market_plugin", "dsh_market_workbench"))
    cli_runtime.reconcile.assert_awaited_once_with(
        cli_runtime.components.facade, (PLUGIN, WORKBENCH), apply=True, operator_id=1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_resource_types"] == ["dsh_market_plugin", "dsh_market_workbench"]
    # The already-registered workbench is reported as kept, not re-registered.
    assert payload["missing_count"] == 1
    assert payload["current_count"] == 2


async def test_default_run_keeps_reconciling_tools_only(cli_runtime, capsys):
    assert await cli.run(cli.parse_args([])) == cli.EXIT_OK
    cli_runtime.market.assert_not_awaited()
    assert json.loads(capsys.readouterr().out)["selected_resource_types"] == ["tool"]


async def test_market_inventory_reads_every_market_record(monkeypatch):
    seen = {}

    async def inventory(resource_types, plugins, workbenches):
        seen.update(types=resource_types, plugins=plugins, workbenches=workbenches)
        return (PLUGIN,)

    monkeypatch.setattr(bootstrap, "system_owned_inventory", inventory)
    assert await bootstrap.load_market_system_owned_inventory(("dsh_market_plugin",)) == (PLUGIN,)
    assert seen["types"] == ("dsh_market_plugin",)
    assert hasattr(seen["plugins"], "all_permission_records")
    assert hasattr(seen["workbenches"], "all_permission_records")

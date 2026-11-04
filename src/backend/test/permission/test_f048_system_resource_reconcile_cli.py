"""System-resource repair CLI keeps dry-run and Store confirmation contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.f048_system_resource_bootstrap import SystemOwnedResourceInventory
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedReconcileReport,
    SystemOwnedResourceSpec,
    SystemOwnedResourceState,
)
from scripts import reconcile_f048_system_owned_resources as cli


def test_apply_requires_store_confirmation():
    assert not cli.parse_args([]).apply
    with pytest.raises(SystemExit):
        cli.parse_args(["--apply"])


@pytest.mark.parametrize("apply", [False, True])
async def test_cli_reports_missing_resources_and_passes_explicit_mode(monkeypatch, capsys, apply):
    spec = SystemOwnedResourceSpec(1, "tool", "902", ("use", "visible"), "preset")
    before = (SystemOwnedResourceState(spec, "MISSING"),)
    after = (SystemOwnedResourceState(spec, "CURRENT", mode="CUSTOM", version=4),) if apply else before
    report = SystemOwnedReconcileReport("apply" if apply else "dry-run", before, after)
    client = SimpleNamespace(store_id="store", model_id="model")
    components = SimpleNamespace(facade=object(), marker=SimpleNamespace(wait_until_ready=AsyncMock()))
    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(
        cli.app_context, "get_context", lambda name: SimpleNamespace(async_get_instance=AsyncMock(return_value=client))
    )
    monkeypatch.setattr(cli, "build_f048_permission_runtime", AsyncMock(return_value=components))
    monkeypatch.setattr(
        cli, "load_system_owned_resource_inventory", AsyncMock(return_value=SystemOwnedResourceInventory((spec,), ()))
    )
    reconcile = AsyncMock(return_value=report)
    monkeypatch.setattr(cli, "reconcile_system_owned_resources", reconcile)
    args = cli.parse_args(["--apply", "--confirm-store-id", "store"] if apply else [])

    assert await cli.run(args) == cli.EXIT_OK

    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == report.mode
    assert payload["missing_count"] == 1
    assert payload["before"][0]["state"] == "MISSING"
    reconcile.assert_awaited_once_with(components.facade, (spec,), apply=apply, operator_id=1)


async def test_store_mismatch_blocks_before_inventory_or_repair(monkeypatch):
    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(
        cli.app_context,
        "get_context",
        lambda name: SimpleNamespace(async_get_instance=AsyncMock(return_value=SimpleNamespace(store_id="live"))),
    )
    inventory = AsyncMock()
    reconcile = AsyncMock()
    monkeypatch.setattr(cli, "load_system_owned_resource_inventory", inventory)
    monkeypatch.setattr(cli, "reconcile_system_owned_resources", reconcile)

    with pytest.raises(cli.SystemResourceReconcileBlockedError, match="Store confirmation mismatch"):
        await cli.run(cli.parse_args(["--apply", "--confirm-store-id", "wrong"]))

    inventory.assert_not_awaited()
    reconcile.assert_not_awaited()

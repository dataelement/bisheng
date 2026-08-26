"""System-owned bootstrap uses the ordinary durable F048 creation path."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application import system_resource_reconcile as reconcile_module
from bisheng.permission.application.system_resource_reconcile import (
    SystemOwnedResourceSpec,
    SystemOwnedResourceState,
    reconcile_system_owned_resources,
)


def _spec(resource_id: str = "6") -> SystemOwnedResourceSpec:
    return SystemOwnedResourceSpec(
        tenant_id=1,
        resource_type="tool",
        resource_id=resource_id,
        action_codes=("use", "visible"),
        context_version=f"tool-{resource_id}",
    )


async def test_dry_run_reports_missing_without_projecting(monkeypatch) -> None:
    spec = _spec()
    missing = (SystemOwnedResourceState(resource=spec, state="MISSING"),)
    inspect = AsyncMock(return_value=missing)
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", inspect)
    runtime = AsyncMock()

    report = await reconcile_system_owned_resources(
        runtime,
        (spec,),
        apply=False,
        operator_id=1,
    )

    assert report.missing_count == 1
    runtime.authorize_system_owned.assert_not_awaited()


async def test_apply_projects_only_missing_resources(monkeypatch) -> None:
    missing_spec = _spec("6")
    current_spec = _spec("16")
    before = (
        SystemOwnedResourceState(resource=missing_spec, state="MISSING"),
        SystemOwnedResourceState(
            resource=current_spec,
            state="CURRENT",
            mode="CUSTOM",
            version=1,
            projection_state="CURRENT",
            operation_id=8,
        ),
    )
    after = tuple(
        SystemOwnedResourceState(
            resource=item.resource,
            state="CURRENT",
            mode="CUSTOM",
            version=1,
            projection_state="CURRENT",
            operation_id=index + 8,
        )
        for index, item in enumerate(before)
    )
    inspect = AsyncMock(side_effect=(before, after))
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", inspect)
    runtime = AsyncMock()

    report = await reconcile_system_owned_resources(
        runtime,
        (current_spec, missing_spec),
        apply=True,
        operator_id=1,
    )

    assert report.current_count == 2
    runtime.authorize_system_owned.assert_awaited_once()
    kwargs = runtime.authorize_system_owned.await_args.kwargs
    assert kwargs["target"].resource_id == "6"
    assert kwargs["action_codes"] == ("use", "visible")
    assert kwargs["idempotency_key"] == "f048:system-bootstrap:1:tool:6"


async def test_non_current_resource_is_never_reinterpreted_as_missing(monkeypatch) -> None:
    spec = _spec()
    inspect = AsyncMock(
        return_value=(
            SystemOwnedResourceState(
                resource=spec,
                state="NON_CURRENT",
                mode="CUSTOM",
                version=1,
                projection_state="FAILED_CLOSED",
                operation_id=9,
            ),
        )
    )
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", inspect)
    runtime = AsyncMock()

    with pytest.raises(PermissionPublishNotReadyError, match="non-current"):
        await reconcile_system_owned_resources(
            runtime,
            (spec,),
            apply=True,
            operator_id=1,
        )

    runtime.authorize_system_owned.assert_not_awaited()

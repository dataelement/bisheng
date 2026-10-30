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


def _runtime():
    runtime = AsyncMock()
    return runtime


async def test_dry_run_reports_missing_without_projecting(monkeypatch) -> None:
    spec = _spec()
    missing = (SystemOwnedResourceState(resource=spec, state="MISSING"),)
    inspect = AsyncMock(return_value=missing)
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", inspect)
    runtime = _runtime()

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
    runtime = _runtime()

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
    runtime = _runtime()

    with pytest.raises(PermissionPublishNotReadyError, match="non-current"):
        await reconcile_system_owned_resources(
            runtime,
            (spec,),
            apply=True,
            operator_id=1,
        )

    runtime.authorize_system_owned.assert_not_awaited()


@pytest.mark.parametrize("fail", [False, True])
async def test_bootstrap_binds_each_verified_tenant_and_restores_caller(monkeypatch, fail):
    from dataclasses import replace

    from bisheng.core.context import tenant

    resources = (_spec("6"), replace(_spec("16"), tenant_id=2))
    missing = tuple(SystemOwnedResourceState(resource=one, state="MISSING") for one in resources)
    current = tuple(SystemOwnedResourceState(resource=one, state="CURRENT") for one in resources)
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", AsyncMock(side_effect=[missing, current]))
    initial = [
        (tenant.current_tenant_id, None),
        (tenant.visible_tenant_ids, frozenset({99})),
        (tenant._admin_scope_tenant_id, 99),
        (tenant._bypass_tenant_filter, False),
    ]
    tokens = [(variable, variable.set(value)) for variable, value in initial]
    observed = []

    async def project(**kwargs):
        target = kwargs["target"]
        assert tenant.get_current_tenant_id() == target.tenant_id
        assert tenant.get_visible_tenant_ids() == frozenset({target.tenant_id})
        assert not tenant.is_tenant_filter_bypassed()
        observed.append(target.tenant_id)
        if fail:
            raise RuntimeError("projection unavailable")

    try:
        runtime = _runtime()
        runtime.authorize_system_owned.side_effect = project
        if fail:
            with pytest.raises(RuntimeError, match="projection unavailable"):
                await reconcile_system_owned_resources(runtime, resources, apply=True, operator_id=1)
        else:
            await reconcile_system_owned_resources(runtime, resources, apply=True, operator_id=1)
            assert observed == [1, 2]
        assert tenant.get_current_tenant_id() == 99
        assert tenant.current_tenant_id.get() is None
        assert tenant.get_visible_tenant_ids() == frozenset({99})
        assert not tenant.is_tenant_filter_bypassed()
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


@pytest.mark.parametrize("resource_type", ["tool", "linsight_skill"])
@pytest.mark.parametrize("apply", [False, True])
async def test_current_resources_preserve_revoked_access_without_legacy_marker_calls(monkeypatch, resource_type, apply):
    from dataclasses import replace
    from types import SimpleNamespace

    spec = replace(_spec("902"), resource_type=resource_type)
    states = (SystemOwnedResourceState(resource=spec, state="CURRENT", mode="CUSTOM", version=3),)
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", AsyncMock(return_value=states))
    # Expose only the supported creation API. A legacy tuple read or repair fails.
    runtime = SimpleNamespace(authorize_system_owned=AsyncMock())
    report = await reconcile_system_owned_resources(runtime, (spec,), apply=apply, operator_id=1)
    assert report.current_count == 1
    assert report.before == report.after == states
    runtime.authorize_system_owned.assert_not_awaited()


async def test_creation_must_reach_current_before_reporting_success(monkeypatch):
    spec = _spec()
    missing = (SystemOwnedResourceState(resource=spec, state="MISSING"),)
    monkeypatch.setattr(reconcile_module, "inspect_system_owned_resources", AsyncMock(return_value=missing))
    runtime = _runtime()
    with pytest.raises(PermissionPublishNotReadyError, match="did not finalize"):
        await reconcile_system_owned_resources(runtime, (spec,), apply=True, operator_id=1)
    runtime.authorize_system_owned.assert_awaited_once()

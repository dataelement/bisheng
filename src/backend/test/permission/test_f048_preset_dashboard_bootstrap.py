"""Preset dashboards receive ordinary owner Grants, never system markers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services import f048_preset_dashboard_bootstrap as bootstrap
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.telemetry_search.domain.models.dashboard import Dashboard
from bisheng.user.domain.services.user import UserService


def _dashboard(resource_id: int, *, owner_user_id: int | None = 1) -> Dashboard:
    return Dashboard(
        id=resource_id,
        tenant_id=1,
        user_id=owner_user_id,
        title="Preset",
        dashboard_type=("preset_oss" if resource_id == 10 else "preset_commercial"),
        status="published",
    )


async def test_missing_samples_project_as_first_user_owned_resources(monkeypatch) -> None:
    dashboards = (_dashboard(10), _dashboard(11))
    current_modes = {
        str(resource_id): SimpleNamespace(
            resource_id=str(resource_id),
            projection_state="CURRENT",
        )
        for resource_id in (10, 11)
    }
    load = AsyncMock(side_effect=((dashboards, {}), (dashboards, current_modes)))
    monkeypatch.setattr(bootstrap, "_load_preset_dashboards_and_modes", load)
    monkeypatch.setattr(bootstrap, "_owner_is_ready", AsyncMock(return_value=True))
    marker = SimpleNamespace(wait_until_ready=AsyncMock())
    facade = SimpleNamespace(authorize_created=AsyncMock())
    monkeypatch.setattr(
        bootstrap,
        "get_f048_process_runtime",
        AsyncMock(return_value=SimpleNamespace(components=SimpleNamespace(marker=marker, facade=facade))),
    )

    report = await bootstrap.reconcile_preset_dashboard_permissions()

    assert report.owner_ready is True
    assert report.resource_count == 2
    assert report.missing_count == 2
    assert report.current_count == 2
    assert facade.authorize_created.await_count == 2
    for call in facade.authorize_created.await_args_list:
        assert call.kwargs["owner_user_id"] == 1
        assert call.kwargs["mode"] == "CUSTOM"
        assert call.kwargs["source_type"] == "CREATOR"
        assert call.kwargs["protected"] is True


async def test_samples_remain_unprojected_until_first_admin_exists(monkeypatch) -> None:
    dashboards = (_dashboard(10), _dashboard(11))
    monkeypatch.setattr(
        bootstrap,
        "_load_preset_dashboards_and_modes",
        AsyncMock(return_value=(dashboards, {})),
    )
    monkeypatch.setattr(bootstrap, "_owner_is_ready", AsyncMock(return_value=False))
    runtime = AsyncMock()
    monkeypatch.setattr(bootstrap, "get_f048_process_runtime", runtime)

    report = await bootstrap.reconcile_preset_dashboard_permissions()

    assert report.owner_ready is False
    assert report.missing_count == 2
    runtime.assert_not_awaited()


async def test_sample_with_no_owner_is_never_reinterpreted_as_system_owned(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_load_preset_dashboards_and_modes",
        AsyncMock(return_value=((_dashboard(10, owner_user_id=None),), {})),
    )

    with pytest.raises(PermissionPublishNotReadyError, match="seeded owner facts"):
        await bootstrap.reconcile_preset_dashboard_permissions()


async def test_only_first_user_creation_triggers_sample_projection(monkeypatch) -> None:
    reconcile = AsyncMock()
    monkeypatch.setattr(bootstrap, "reconcile_preset_dashboard_permissions", reconcile)
    monkeypatch.setattr(
        "bisheng.user.domain.services.user.settings.openfga.enabled",
        True,
    )

    await UserService.areconcile_first_user_dashboard_permissions(2)
    await UserService.areconcile_first_user_dashboard_permissions(1)

    reconcile.assert_awaited_once_with()

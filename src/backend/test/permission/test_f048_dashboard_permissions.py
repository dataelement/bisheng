"""F048 dashboard action and lifecycle contracts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.telemetry_search.domain.models.dashboard import (
    Dashboard,
    DashboardComponent,
    DashboardStatus,
    DashboardType,
)
from bisheng.telemetry_search.domain.services.dashboard import (
    DASHBOARD_OPERATION_ACTIONS,
    DashboardResourceAuthorizationPort,
    DashboardService,
)
from bisheng.telemetry_search.domain.services.f048_dashboard_permission import (
    DashboardPermissionRecord,
    F048DashboardPermissionAdapter,
)


class _Loader:
    def __init__(self, records: tuple[DashboardPermissionRecord, ...]):
        self.records = {record.resource_id: record for record in records}

    async def load_permission_record(self, resource_id):
        return self.records.get(resource_id)


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    async def check_action(self, actor, target, action):
        self.calls.append(("check", (actor, target, action)))
        if self.error:
            raise self.error
        return True

    async def batch_check_actions(self, actor, targets, action):
        self.calls.append(("batch", (actor, targets, action)))
        return tuple(True for _ in targets)

    async def authorize_created(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "FINALIZED"}

    async def authorize_system_owned(self, **kwargs):
        self.calls.append(("system", kwargs))
        return {"status": "FINALIZED"}

    async def project_copy(self, **kwargs):
        self.calls.append(("copy", kwargs))
        return {"status": "FINALIZED"}


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


def _record(
    *,
    tenant_id: int = 5,
    dashboard_type: str = "custom",
    status: str = "draft",
    system_allowlisted: bool = False,
) -> DashboardPermissionRecord:
    return DashboardPermissionRecord(
        tenant_id=tenant_id,
        resource_id="41",
        dashboard_type=dashboard_type,
        status=status,
        owner_user_id=None if dashboard_type != "custom" else 7,
        permission_version=4,
        context_version="dashboard-41-v4",
        system_allowlisted=system_allowlisted,
    )


def test_every_dashboard_operation_maps_to_the_required_exact_action() -> None:
    assert DASHBOARD_OPERATION_ACTIONS == {
        "list": "visible",
        "detail": "visible",
        "component_data": "visible",
        "copy_source": "visible",
        "set_default": "visible",
        "share_link": "visible",
        "title": "edit",
        "status": "edit",
        "layout": "edit",
        "component": "edit",
        "delete": "delete",
        "members": "manage_permission",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    ("visible", "edit", "delete", "manage_permission"),
)
async def test_custom_dashboard_uses_exact_action(action) -> None:
    permission = _Permission()
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_id="41",
        actor=_actor(),
        action=action,
    )
    assert permission.calls[0][1][2] == action


@pytest.mark.asyncio
async def test_dashboard_business_port_builds_verified_target() -> None:
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=_Permission(),
    )
    target = await DashboardResourceAuthorizationPort(adapter).resolve_permission_target(
        resource_id="41",
        actor=_actor(),
        action="visible",
    )

    assert target.resource_type == "dashboard"
    assert target.tenant_id == 5


@pytest.mark.asyncio
async def test_custom_create_projects_protected_owner() -> None:
    permission = _Permission()
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=permission,
    )

    await adapter.authorize_created(record=_record(), actor=_actor())

    create = permission.calls[0][1]
    assert create["owner_user_id"] == 7
    assert create["mode"] == "CUSTOM"
    assert create["protected"] is True


@pytest.mark.asyncio
async def test_dashboard_copy_preserves_custom_grants_and_regenerates_owner() -> None:
    permission = _Permission()
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=permission,
    )
    target = replace(
        _record(),
        resource_id="42",
        owner_user_id=8,
        permission_version=0,
        context_version="dashboard-42-create",
    )

    await adapter.project_copy(
        source=_record(),
        target=target,
        actor=_actor(),
        new_owner_user_id=8,
    )

    copy = permission.calls[0][1]
    assert copy["source"].resource_id == "41"
    assert copy["target"].resource_id == "42"
    assert copy["owner_user_id"] == 8
    assert copy["mode"] == "CUSTOM"


@pytest.mark.asyncio
async def test_preset_dashboard_requires_predicate_and_is_visible_only() -> None:
    preset = _record(
        dashboard_type="preset_commercial",
        status="published",
        system_allowlisted=True,
    )
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((preset,)),
        permission=_Permission(),
    )

    assert await adapter.check_action(
        resource_id="41",
        actor=_actor(),
        action="visible",
    )
    with pytest.raises(InvalidCatalogActionError):
        await adapter.check_action(
            resource_id="41",
            actor=_actor(),
            action="edit",
        )

    blocked = replace(preset, system_allowlisted=False)
    with pytest.raises(PermissionInvalidResourceError):
        await F048DashboardPermissionAdapter(
            loader=_Loader((blocked,)),
            permission=_Permission(),
        ).resolve_permission_target(
            resource_id="41",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_dashboard_fga_failure_never_falls_back_to_access_type() -> None:
    permission = _Permission()
    permission.error = PermissionFGAUnavailableError()
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=permission,
    )

    with pytest.raises(PermissionFGAUnavailableError):
        await adapter.check_action(
            resource_id="41",
            actor=_actor(),
            action="visible",
        )
    assert len(permission.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    (
        None,
        _record(tenant_id=6),
        _record(status="deleted"),
        _record(dashboard_type="unknown"),
    ),
)
async def test_invalid_dashboard_business_facts_fail_closed(record) -> None:
    records = tuple(row for row in (record,) if row is not None)
    adapter = F048DashboardPermissionAdapter(
        loader=_Loader(records),
        permission=_Permission(),
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id="41",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_copy_preset_creates_custom_dashboard_owned_by_copier(
    monkeypatch,
) -> None:
    source = Dashboard(
        id=41,
        tenant_id=5,
        user_id=None,
        title="Preset",
        dashboard_type=DashboardType.PRESET_COMMERCIAL.value,
        status=DashboardStatus.PUBLISHED.value,
    )
    inserted: list[Dashboard] = []

    async def insert_dashboard(dashboard):
        dashboard.id = 42
        inserted.append(dashboard)
        return dashboard

    source_permission = _record(
        dashboard_type=DashboardType.PRESET_COMMERCIAL.value,
        status=DashboardStatus.PUBLISHED.value,
        system_allowlisted=True,
    )
    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=source_permission),
        project_copy=AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_one",
        AsyncMock(return_value=source),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.count_dashboards",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_components",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.insert",
        insert_dashboard,
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.insert_components",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.get_f048_resource_adapter",
        lambda resource_type: adapter,
    )
    service = DashboardService(
        login_user=UserPayload(
            user_id=7,
            tenant_id=6,
            user_name="copier",
            user_role=[],
            is_global_super=False,
        )
    )
    service._require_action = AsyncMock()
    monkeypatch.setattr(
        DashboardService,
        "create_dashboard_hook",
        AsyncMock(),
    )

    copied = await service.copy_dashboard(41, "My dashboard")

    assert copied is inserted[0]
    assert copied.dashboard_type == DashboardType.CUSTOM.value
    assert copied.tenant_id == 6
    assert copied.user_id == 7
    projected = adapter.project_copy.await_args.kwargs["target"]
    assert projected.dashboard_type == DashboardType.CUSTOM.value
    assert projected.owner_user_id == 7
    assert adapter.project_copy.await_args.kwargs["source"] is source_permission
    assert adapter.project_copy.await_args.kwargs["new_owner_user_id"] == 7


@pytest.mark.asyncio
async def test_copy_projection_failure_removes_committed_dashboard(
    monkeypatch,
) -> None:
    source = Dashboard(
        id=41,
        tenant_id=5,
        user_id=7,
        title="Source",
        dashboard_type=DashboardType.CUSTOM.value,
        status=DashboardStatus.DRAFT.value,
    )
    inserted = Dashboard(
        id=42,
        tenant_id=5,
        user_id=7,
        title="Copy",
        dashboard_type=DashboardType.CUSTOM.value,
        status=DashboardStatus.DRAFT.value,
    )
    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=_record()),
        project_copy=AsyncMock(
            side_effect=PermissionFGAUnavailableError(),
        ),
    )
    delete_one = AsyncMock()
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_one",
        AsyncMock(return_value=source),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.count_dashboards",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_components",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.insert",
        AsyncMock(return_value=inserted),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.delete_one",
        delete_one,
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.get_f048_resource_adapter",
        lambda resource_type: adapter,
    )
    service = DashboardService(
        login_user=UserPayload(
            user_id=7,
            tenant_id=5,
            user_role=[],
        )
    )
    service._require_action = AsyncMock()

    with pytest.raises(PermissionFGAUnavailableError):
        await service.copy_dashboard(41, "Copy")

    delete_one.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_component_query_rejects_component_from_other_dashboard(
    monkeypatch,
) -> None:
    dashboard = Dashboard(
        id=41,
        tenant_id=5,
        user_id=7,
        title="Allowed",
        dashboard_type=DashboardType.CUSTOM.value,
        status=DashboardStatus.DRAFT.value,
    )
    foreign_component = DashboardComponent(
        id="component-1",
        dashboard_id=99,
        dataset_code="telemetry",
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_one",
        AsyncMock(return_value=dashboard),
    )
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.services.dashboard.DashboardDao.get_one_component",
        AsyncMock(return_value=foreign_component),
    )
    service = DashboardService(
        login_user=UserPayload(
            user_id=7,
            tenant_id=5,
            user_role=[],
        )
    )
    service._require_action = AsyncMock()

    with pytest.raises(NotFoundError):
        await service.query_component_data(
            41,
            component_id="component-1",
        )

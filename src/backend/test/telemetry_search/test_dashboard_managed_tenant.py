"""Managed dashboard writes use the selected tenant and leave no failed inserts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import InvalidRequestError
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionFGAUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope, visible_tenant_ids
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.telemetry_search.domain.models.dashboard import (
    Dashboard,
    DashboardComponent,
    DashboardDefault,
    DashboardType,
)
from bisheng.telemetry_search.domain.models.dashboard_dao import DashboardDao
from bisheng.telemetry_search.domain.schemas.dashboard import DashboardCreate
from bisheng.telemetry_search.domain.services import dashboard as dashboard_module
from bisheng.telemetry_search.domain.services.dashboard import DashboardService
from bisheng.telemetry_search.domain.services.f048_dashboard_permission import F048DashboardPermissionAdapter
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.mark.parametrize("home,target", [(1, 1), (60, 60), (1, 60)])
@pytest.mark.parametrize("operation", ["create", "copy"])
async def test_dashboard_write_and_permission_projection_use_managed_tenant(
    monkeypatch, managed_db, home, target, operation
):
    await managed_db.create(Dashboard, DashboardComponent, DashboardDefault)
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.models.dashboard_dao.get_async_db_session",
        managed_db.sessions,
    )
    monkeypatch.setattr(dashboard_module, "is_commercial", lambda: True)
    monkeypatch.setattr(UserPayload, "async_access_check", AsyncMock(return_value=True))
    monkeypatch.setattr(DashboardService, "create_dashboard_hook", AsyncMock())
    monkeypatch.setattr(DashboardService, "_require_action", AsyncMock())
    actor = PermissionActor(user_id=3, tenant_id=home, super_admin=home == 1)
    resolve_actor = AsyncMock(return_value=actor)
    monkeypatch.setattr(dashboard_module, "resolve_permission_actor", resolve_actor)
    permission = SimpleNamespace(
        authorize_created=AsyncMock(),
        project_copy=AsyncMock(),
    )
    loader = SimpleNamespace(load_permission_record=AsyncMock())
    adapter = F048DashboardPermissionAdapter(loader=loader, permission=permission)
    monkeypatch.setattr(dashboard_module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    user = UserPayload(user_id=3, tenant_id=home, user_role=[], is_global_super=home == 1)
    service = DashboardService(login_user=user)

    with management_scope(home=home, target=target):
        if operation == "create":
            created = await service.create_dashboard(DashboardCreate(title="Managed"))
            projection = permission.authorize_created.await_args.kwargs
        else:
            source = await DashboardDao.insert(Dashboard(tenant_id=target, user_id=3))
            loader.load_permission_record.return_value = service._new_permission_record(source)
            created = await service.copy_dashboard(source.id, "Managed copy")
            projection = permission.project_copy.await_args.kwargs
        record = projection["target"]
        persisted = await DashboardDao.get_one(created.id)
        assert persisted is not None
        assert persisted.tenant_id == target
        assert persisted.user_id == 3
        assert record.tenant_id == target
        assert record.resource_id == str(persisted.id)
        assert projection["actor"] is actor
        resolve_actor.assert_awaited_once_with(user)
        assert user.tenant_id == home  # Switching views must not rewrite identity.


@pytest.mark.parametrize("operation", ["create", "copy"])
async def test_permission_failure_removes_new_dashboard_in_managed_tenant(monkeypatch, managed_db, operation):
    await managed_db.create(Dashboard, DashboardComponent, DashboardDefault)
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.models.dashboard_dao.get_async_db_session",
        managed_db.sessions,
    )
    monkeypatch.setattr(dashboard_module, "is_commercial", lambda: True)
    monkeypatch.setattr(UserPayload, "async_access_check", AsyncMock(return_value=True))
    monkeypatch.setattr(DashboardService, "_require_action", AsyncMock())
    monkeypatch.setattr(dashboard_module, "resolve_permission_actor", AsyncMock())
    adapter = SimpleNamespace(
        authorize_created=AsyncMock(side_effect=PermissionFGAUnavailableError()),
        load_permission_record=AsyncMock(return_value=object()),
        project_copy=AsyncMock(side_effect=PermissionFGAUnavailableError()),
    )
    monkeypatch.setattr(dashboard_module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    service = DashboardService(login_user=UserPayload(user_id=3, tenant_id=1, user_role=[], is_global_super=True))
    with management_scope(home=1, target=60):
        source = await DashboardDao.insert(Dashboard(tenant_id=60, user_id=3))
        with pytest.raises(PermissionFGAUnavailableError):
            if operation == "create":
                await service.create_dashboard(DashboardCreate(title="Failed create"))
            else:
                await service.copy_dashboard(source.id, "Failed copy")
        with bypass_tenant_filter():
            async with managed_db.sessions() as session:
                rows = (await session.exec(select(Dashboard))).all()
                assert [row.id for row in rows] == [source.id]


async def test_refresh_failure_does_not_commit_orphan_dashboard(monkeypatch, managed_db):
    await managed_db.create(Dashboard)
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.models.dashboard_dao.get_async_db_session",
        managed_db.sessions,
    )
    with management_scope(home=1, target=60):
        # Reproduce the original wrong-tenant write and its tenant-filtered refresh.
        with pytest.raises(InvalidRequestError, match="Could not refresh"):
            await DashboardDao.insert(Dashboard(tenant_id=1, user_id=3))
        with bypass_tenant_filter():
            async with managed_db.sessions() as session:
                assert (await session.exec(select(Dashboard))).all() == []


async def test_child_admin_can_create_without_ordinary_menu_grant(monkeypatch, managed_db):
    await managed_db.create(Dashboard, DashboardComponent, DashboardDefault)
    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.models.dashboard_dao.get_async_db_session", managed_db.sessions
    )
    monkeypatch.setattr(dashboard_module, "is_commercial", lambda: True)
    menu = AsyncMock(return_value=False)
    monkeypatch.setattr(UserPayload, "async_access_check", menu)
    monkeypatch.setattr(DashboardService, "create_dashboard_hook", AsyncMock())
    actor = PermissionActor(user_id=7, tenant_id=2, tenant_admin_tenant_ids=frozenset({2}))
    monkeypatch.setattr(dashboard_module, "resolve_permission_actor", AsyncMock(return_value=actor))
    permission = SimpleNamespace(authorize_created=AsyncMock())
    monkeypatch.setattr(dashboard_module, "get_f048_resource_adapter", AsyncMock(return_value=permission))
    user = UserPayload(user_id=7, tenant_id=2, user_role=[])
    with tenant_execution_scope(1):
        for i in range(20):
            await DashboardDao.insert(
                Dashboard(tenant_id=1, user_id=3, title=f"Root {i}", dashboard_type=DashboardType.CUSTOM.value)
            )
    with tenant_execution_scope(2):
        token = visible_tenant_ids.set(frozenset({1, 2}))
        try:
            row = await DashboardService(login_user=user).create_dashboard(DashboardCreate(title="Child admin"))
            assert row.tenant_id == 2 and row.user_id == 7
            assert (await DashboardDao.get_one(row.id)).tenant_id == 2
        finally:
            visible_tenant_ids.reset(token)
    menu.assert_not_awaited()
    assert permission.authorize_created.await_args.kwargs["record"].tenant_id == 2

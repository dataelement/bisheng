"""Exercise the real app UNION and cursor scan under tenant-admin scope."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine

import bisheng.api.services.workflow as workflow_module
import bisheng.database.models.flow as flow_module
from bisheng.api.services.workflow import WorkFlowService
from bisheng.core.context.tenant import (
    current_tenant_id,
    is_strict_tenant_filter,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.database.models.flow import FlowDao
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def app_list_context(monkeypatch):
    tenant_token = set_current_tenant_id(60)
    visible_token = set_visible_tenant_ids(frozenset({1, 60}))
    monkeypatch.setattr(workflow_module.settings.app_runtime, "enabled", True)
    monkeypatch.setattr(WorkFlowService, "add_extra_field", lambda _user, rows, *_args, **_kwargs: rows)
    monkeypatch.setattr(workflow_module, "emit_metric", lambda *_args, **_kwargs: None)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for table, description, owner, extra in (
            ("flow", "description", "user_id", "flow_type INTEGER DEFAULT 10, status INTEGER DEFAULT 1"),
            ("assistant", "desc", "user_id", "is_delete INTEGER DEFAULT 0, status INTEGER DEFAULT 1"),
            ("app", "description", "owner_user_id", "state TEXT DEFAULT 'draft'"),
        ):
            connection.exec_driver_sql(
                f"CREATE TABLE {table} (id TEXT, name TEXT, {description} TEXT, logo TEXT, "
                f"{owner} INTEGER, create_time DATETIME, update_time DATETIME, tenant_id INTEGER, {extra})"
            )
            for tenant in (1, 60, 61):
                # All apps belong to someone other than the requesting admin.
                connection.exec_driver_sql(
                    f"INSERT INTO {table} (id, name, {owner}, tenant_id, create_time, update_time) "
                    "VALUES (?, ?, 777, ?, '2026-10-29T10:00:00', '2026-10-29T10:00:00')",
                    (f"{table}-{tenant}", f"{table}-{tenant}", tenant),
                )

        class ReadSession:
            async def exec(self, statement):
                return connection.execute(statement)

        @asynccontextmanager
        async def session():
            yield ReadSession()

        monkeypatch.setattr(flow_module, "get_async_db_session", session)
        try:
            yield
        finally:
            current_tenant_id.reset(tenant_token)
            visible_tenant_ids.reset(visible_token)
    engine.dispose()


async def _list(monkeypatch, *, super_admin=False, managed=True, **kwargs):
    actor = PermissionActor(
        user_id=849,
        current_tenant_id=60,
        super_admin=super_admin,
        tenant_admin_tenant_ids=frozenset({60}),
    )
    monkeypatch.setattr(workflow_module, "resolve_permission_actor", AsyncMock(return_value=actor))
    return await WorkFlowService.get_all_flows_envelope(
        SimpleNamespace(user_id=849, tenant_id=60),
        name=None,
        status=None,
        tag_id=None,
        flow_type=None,
        managed=managed,
        **kwargs,
    )


async def test_tenant_admin_lists_other_owners_apps_only_in_current_tenant(app_list_context, monkeypatch):
    first = await _list(monkeypatch, page_size=2)
    second = await _list(monkeypatch, page_size=2, cursor=first.next_cursor)
    assert first.has_more is True
    assert second.has_more is False
    assert {row["id"] for row in first.data + second.data} == {"flow-60", "assistant-60", "app-60"}
    assert is_strict_tenant_filter() is False
    # The request's readable scope is restored; shared reads still see root rows.
    shared, _ = await FlowDao.aget_all_apps(limit=20)
    assert {row["id"] for row in shared} == {"flow-1", "assistant-1", "app-1", "flow-60", "assistant-60", "app-60"}


async def test_super_admin_keeps_existing_scope(app_list_context, monkeypatch):
    result = await _list(monkeypatch, super_admin=True, page_size=20)
    assert len(result.data) == 6
    assert is_strict_tenant_filter() is False


async def test_unmanaged_list_does_not_enter_management_scope(app_list_context, monkeypatch):
    async def scan(**_kwargs):
        assert is_strict_tenant_filter() is False
        return [], False, set()

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", scan)
    await _list(monkeypatch, managed=False)


async def test_failed_list_restores_scope(app_list_context, monkeypatch):
    async def fail(**_kwargs):
        assert is_strict_tenant_filter() is True
        raise TimeoutError("database unavailable")

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", fail)
    with pytest.raises(TimeoutError):
        await _list(monkeypatch)
    assert is_strict_tenant_filter() is False
    assert visible_tenant_ids.get() == frozenset({1, 60})

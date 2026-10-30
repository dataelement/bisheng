"""F114: service-account management keeps the verified view and deleted-app cleanup works."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.domain.services.f048_app_permission import (
    AppDaoPermissionLoader,
    AppPermissionRecord,
    F048AppPermissionAdapter,
)
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.open_api.domain.services import service_account_scope_service as scopes
from bisheng.permission.domain.services.permission_action_service import PermissionActor


async def test_service_account_view_reaches_app_target_without_changing_actor(monkeypatch):
    monkeypatch.setattr(scopes.settings.multi_tenant, "enabled", True)
    monkeypatch.setattr(scopes, "current_admin_scope", AsyncMock(return_value=63))
    monkeypatch.setattr(scopes, "ensure_service_account_tenant_available", AsyncMock())
    actor = PermissionActor(user_id=867, current_tenant_id=1, super_admin=True)
    record = AppPermissionRecord(63, "app", "draft", 875, 1, "context")
    adapter = F048AppPermissionAdapter(loader=None, permission=None)
    operator = SimpleNamespace(user_id=867, tenant_id=1, is_global_super=True)
    async with scopes.ServiceAccountScopeService.bind_request(operator, expected_tenant="63", writing=True):
        assert adapter._target(record, "app", actor).tenant_id == 63
        assert actor.current_tenant_id == 1
        with pytest.raises(PermissionInvalidResourceError):
            adapter._target(AppPermissionRecord(64, "other", "draft", 875, 1, "context"), "other", actor)


@pytest.mark.parametrize("state", ["deleted", "draft"])
async def test_deleted_app_has_no_permission_record_for_account_cleanup(monkeypatch, state):
    import bisheng.core.database as database
    from bisheng.database.models.app import AppDao

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(database, "get_async_db_session", session)
    monkeypatch.setattr(
        AppDao,
        "aget",
        AsyncMock(
            return_value=SimpleNamespace(
                id="app",
                tenant_id=63,
                state=state,
                owner_user_id=875,
                update_time=None,
            )
        ),
    )
    versions = SimpleNamespace(get_permission_version=AsyncMock(return_value=(1, "context")))
    result = await AppDaoPermissionLoader(versions).load_permission_record("app")
    if state == "deleted":
        assert result is None
        versions.get_permission_version.assert_not_awaited()
    else:
        assert result.tenant_id == 63 and result.state == "draft"
        versions.get_permission_version.assert_awaited_once()

"""An explicit bootstrap is the only place allowed to establish the default view."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.admin.api.endpoints import request_scope
from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.errcode.admin_scope import AdminScopeTenantRequiredError, AdminScopeUnavailableError


@pytest.mark.parametrize("initialize", [False, True])
async def test_missing_selection_only_bootstraps_explicitly(monkeypatch, initialize):
    monkeypatch.setattr(TenantScopeService, "get_scope", AsyncMock(side_effect=AdminScopeTenantRequiredError()))
    save = AsyncMock(return_value={"scope_tenant_id": 1, "source": "selected", "expires_at": None})
    monkeypatch.setattr(TenantScopeService, "set_scope", save)
    result = await request_scope._read(
        SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True), initialize=initialize
    )
    if initialize:
        assert result.data["scope_tenant_id"] == 1
        save.assert_awaited_once_with(191, 1)
    else:
        assert result.status_code == 400
        save.assert_not_awaited()


async def test_unknown_preference_does_not_create_a_default(monkeypatch):
    monkeypatch.setattr(TenantScopeService, "get_scope", AsyncMock(side_effect=AdminScopeUnavailableError()))
    save = AsyncMock()
    monkeypatch.setattr(TenantScopeService, "set_scope", save)
    result = await request_scope._read(SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True), initialize=True)
    assert result.status_code == 503
    save.assert_not_awaited()


async def test_audit_failure_reports_unknown_after_preference_write(monkeypatch):
    from bisheng.admin.domain.services import tenant_scope as domain

    monkeypatch.setattr(TenantScopeService, "get_scope", AsyncMock(return_value={"scope_tenant_id": 1}))
    monkeypatch.setattr(TenantScopeService, "_own_tenant", AsyncMock(return_value=1))
    monkeypatch.setattr(domain.TenantScopeRepository, "status", AsyncMock(return_value="active"))
    redis = SimpleNamespace(aset=AsyncMock())
    monkeypatch.setattr(domain, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(domain.AuditLogDao, "ainsert_v2", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    with pytest.raises(AdminScopeUnavailableError):
        await TenantScopeService.set_scope(191, 60)
    redis.aset.assert_awaited_once()
    assert redis.aset.call_args.args[1] == "60"

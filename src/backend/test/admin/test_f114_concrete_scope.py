"""F114 AC-09 through AC-18: one verified tenant, never a global fallback."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.admin_scope import (
    AdminScopeTenantNotFoundError,
    AdminScopeTenantRequiredError,
    AdminScopeUnavailableError,
)


@pytest.fixture
def scope_policy(monkeypatch):
    from bisheng.admin.domain.services import tenant_scope as mod

    redis = SimpleNamespace(
        aget=AsyncMock(return_value=None),
        attl=AsyncMock(return_value=100),
        aset=AsyncMock(),
        adelete=AsyncMock(),
        aexpire_key=AsyncMock(),
    )
    monkeypatch.setattr(mod, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(
        mod, "settings", SimpleNamespace(multi_tenant=SimpleNamespace(enabled=True, admin_scope_ttl_seconds=14400))
    )
    from bisheng.admin.domain.repositories.tenant_scope_repository import TenantScopeRepository

    monkeypatch.setattr(TenantScopeRepository, "own_tenant_ids", AsyncMock(return_value=(2,)), raising=False)
    monkeypatch.setattr(TenantScopeRepository, "status", AsyncMock(return_value="active"))
    audit = AsyncMock()
    monkeypatch.setattr(mod.AuditLogDao, "ainsert_v2", audit)
    return mod, redis, TenantScopeRepository, audit


@pytest.mark.parametrize("value", [None, "bad", "", "0", "-1", "True"])
async def test_missing_or_invalid_selection_resolves_own(scope_policy, value):
    mod, redis, _repo, _audit = scope_policy
    redis.aget.return_value = value
    result = await mod.TenantScopeService.get_scope(42, is_super=True)
    assert result["scope_tenant_id"] == 2
    assert result["source"] == "own"
    redis.adelete.assert_not_awaited()


async def test_valid_selection_reports_one_tenant(scope_policy):
    mod, redis, _repo, _audit = scope_policy
    redis.aget.return_value = "3"
    result = await mod.TenantScopeService.get_scope(42, is_super=True)
    assert result["scope_tenant_id"] == 3
    assert result["source"] == "selected"
    assert result["expires_at"] is not None


@pytest.mark.parametrize("status", [None, "disabled", "archived"])
async def test_unavailable_selection_falls_back_to_validated_own(scope_policy, status):
    mod, redis, repo, _audit = scope_policy
    redis.aget.return_value = "3"
    repo.status.side_effect = lambda tid: status if tid == 3 else "active"
    result = await mod.TenantScopeService.get_scope(42, is_super=True)
    assert result["scope_tenant_id"] == 2
    assert result["source"] == "own"


async def test_non_super_does_not_read_historical_selection(scope_policy):
    mod, redis, _repo, _audit = scope_policy
    redis.aget.return_value = "3"
    result = await mod.TenantScopeService.get_scope(42, is_super=False)
    assert result["scope_tenant_id"] == 2
    redis.aget.assert_not_awaited()


@pytest.mark.parametrize("tenants", [(), (2, 3)])
async def test_no_unique_own_tenant_refuses_data(scope_policy, tenants):
    mod, _redis, repo, _audit = scope_policy
    repo.own_tenant_ids.return_value = tenants
    with pytest.raises(AdminScopeUnavailableError):
        await mod.TenantScopeService.get_scope(42, is_super=False)


@pytest.mark.parametrize("target", [None, 0, -1, True, "3", "global"])
async def test_invalid_switch_never_clears_existing_selection(scope_policy, target):
    mod, redis, _repo, audit = scope_policy
    redis.aget.return_value = "3"
    with pytest.raises(AdminScopeTenantRequiredError):
        await mod.TenantScopeService.set_scope(42, target)
    redis.aset.assert_not_awaited()
    redis.adelete.assert_not_awaited()
    audit.assert_not_awaited()


async def test_disabled_switch_preserves_existing_selection(scope_policy):
    mod, redis, repo, _audit = scope_policy
    repo.status.return_value = "disabled"
    with pytest.raises(AdminScopeTenantNotFoundError):
        await mod.TenantScopeService.set_scope(42, 3)
    redis.aset.assert_not_awaited()
    redis.adelete.assert_not_awaited()


async def test_switch_audits_actual_from_and_to(scope_policy):
    mod, redis, _repo, audit = scope_policy
    redis.aget.return_value = "3"
    result = await mod.TenantScopeService.set_scope(42, 1)
    assert result["scope_tenant_id"] == 1
    assert result["source"] == "selected"
    assert audit.await_args.kwargs["metadata"]["from_scope"] == 3
    assert audit.await_args.kwargs["metadata"]["to_scope"] == 1
    assert audit.await_args.kwargs["operator_tenant_id"] == 2


async def test_redis_uncertainty_only_allows_verified_own_reads(scope_policy):
    mod, redis, _repo, _audit = scope_policy
    redis.aget.side_effect = ConnectionError("unavailable")
    assert (await mod.TenantScopeService.get_scope(42, is_super=True))["scope_tenant_id"] == 2
    with pytest.raises(AdminScopeUnavailableError):
        await mod.TenantScopeService.get_scope(42, is_super=True, for_write=True)

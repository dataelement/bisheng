"""Unit tests for TenantAdminService (F013 T07).

Covers:
- Root tenant guard (id == 1 fast path AND parent_tenant_id IS NULL defensive)
- grant/revoke success path forwards correct FGA tuple
- FGA unavailable raises OpenFGAConnectionError
- list_tenant_admins returns [] for Root, parses user ids from tuples
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant import TenantNotFoundError
from bisheng.common.errcode.tenant_fga import (
    OpenFGAConnectionError,
    RootTenantAdminNotAllowedError,
)
from bisheng.permission.domain.services.tenant_admin_service import TenantAdminService


# ── _guard_not_root ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_rejects_root_by_id_short_circuit():
    """tenant_id == 1 must short-circuit before any DB / FGA call."""
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client') as get_fga:
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(tenant_id=1, user_id=10)
        dao.aget_by_id.assert_not_called()
        get_fga.assert_not_called()


@pytest.mark.asyncio
async def test_grant_rejects_when_parent_tenant_id_null():
    """Defensive: any tenant with parent_tenant_id=None is treated as Root."""
    fake_tenant = SimpleNamespace(id=99, parent_tenant_id=None)
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao:
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(tenant_id=99, user_id=10)


@pytest.mark.asyncio
async def test_grant_raises_tenant_not_found_when_missing():
    """Missing tenant now raises TenantNotFoundError (20000) — distinct from Root (19204)."""
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao:
        dao.aget_by_id = AsyncMock(return_value=None)
        with pytest.raises(TenantNotFoundError):
            await TenantAdminService.grant_tenant_admin(tenant_id=99, user_id=10)


# ── grant happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_success_for_child_tenant():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()

    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)

    fake_fga.write_tuples.assert_awaited_once_with(writes=[{
        'user': 'user:10', 'relation': 'admin', 'object': 'tenant:5',
    }])


@pytest.mark.asyncio
async def test_grant_raises_when_fga_unavailable():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=None)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        with pytest.raises(OpenFGAConnectionError):
            await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)


# ── revoke ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_success_for_child_tenant():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()

    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.revoke_tenant_admin(tenant_id=5, user_id=10)

    fake_fga.write_tuples.assert_awaited_once_with(deletes=[{
        'user': 'user:10', 'relation': 'admin', 'object': 'tenant:5',
    }])


@pytest.mark.asyncio
async def test_revoke_rejects_root_short_circuit():
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao:
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.revoke_tenant_admin(tenant_id=1, user_id=10)
        dao.aget_by_id.assert_not_called()


# ── list_tenant_admins ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_admins_returns_empty_for_root():
    """Root short-circuits without touching FGA."""
    with patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client') as get_fga:
        result = await TenantAdminService.list_tenant_admins(tenant_id=1)
    assert result == []
    get_fga.assert_not_called()


@pytest.mark.asyncio
async def test_list_admins_returns_empty_when_fga_unavailable():
    with patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=None)):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)
    assert result == []


@pytest.mark.asyncio
async def test_list_admins_parses_user_ids():
    fake_fga = MagicMock()
    fake_fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:7', 'relation': 'admin', 'object': 'tenant:5'},
        {'user': 'user:9', 'relation': 'admin', 'object': 'tenant:5'},
    ])
    with patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)

    assert sorted(result) == [7, 9]


@pytest.mark.asyncio
async def test_list_admins_skips_non_numeric_users():
    fake_fga = MagicMock()
    fake_fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:7'},
        {'user': 'user:foo'},  # malformed; skipped
        {'user': 'department:5#member'},  # not a user; skipped
    ])
    with patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)

    assert result == [7]

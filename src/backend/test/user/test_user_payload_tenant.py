"""Unit tests for UserPayload F013 stubs (T06).

Verifies get_visible_tenants and has_tenant_admin behave correctly under
the MVP 2-layer rule and Root-tenant invariants.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def payload_factory():
    """Build a UserPayload bypassing __init__ DB lookups (UserRoleDao)."""
    def _factory(user_id: int = 100, tenant_id: int = 1):
        with patch('bisheng.user.domain.services.auth.UserRoleDao') as urd:
            urd.get_user_roles.return_value = []
            return UserPayload(
                user_id=user_id,
                user_name='tester',
                user_role=[],
                tenant_id=tenant_id,
            )
    return _factory


# ── get_visible_tenants ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_visible_tenants_reads_context_var_when_set(payload_factory):
    """Primary path: F012 middleware set the ContextVar → no DB lookup."""
    user = payload_factory(user_id=100)

    from bisheng.core.context.tenant import set_visible_tenant_ids
    token = set_visible_tenant_ids(frozenset({5, 1}))
    try:
        with patch('bisheng.database.models.tenant.UserTenantDao') as dao:
            dao.aget_active_user_tenant = AsyncMock()
            result = await user.get_visible_tenants()
            dao.aget_active_user_tenant.assert_not_called()
    finally:
        from bisheng.core.context.tenant import visible_tenant_ids
        visible_tenant_ids.reset(token)

    assert result == [5, 1]  # leaf first, root last


@pytest.mark.asyncio
async def test_visible_tenants_context_var_root_only(payload_factory):
    """Root-only visible set (single element frozenset) returns [1]."""
    user = payload_factory(user_id=100)

    from bisheng.core.context.tenant import set_visible_tenant_ids, visible_tenant_ids
    token = set_visible_tenant_ids(frozenset({1}))
    try:
        result = await user.get_visible_tenants()
    finally:
        visible_tenant_ids.reset(token)

    assert result == [1]


@pytest.mark.asyncio
async def test_visible_tenants_dedupes_when_leaf_is_root_fallback(payload_factory):
    """Fallback path: ContextVar unset + DAO returns Root leaf → [1]."""
    user = payload_factory(user_id=100)

    fake_active = SimpleNamespace(tenant_id=1)
    with patch('bisheng.database.models.tenant.UserTenantDao') as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=fake_active)
        result = await user.get_visible_tenants()

    assert result == [1]


@pytest.mark.asyncio
async def test_visible_tenants_child_returns_leaf_plus_root_fallback(payload_factory):
    """Fallback path: ContextVar unset + DAO returns Child leaf → [leaf, 1]."""
    user = payload_factory(user_id=100)

    fake_active = SimpleNamespace(tenant_id=5)
    with patch('bisheng.database.models.tenant.UserTenantDao') as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=fake_active)
        result = await user.get_visible_tenants()

    assert result == [5, 1]


@pytest.mark.asyncio
async def test_visible_tenants_no_active_falls_back_to_root(payload_factory):
    """Fallback path: ContextVar unset + no active UserTenant → [Root]."""
    user = payload_factory(user_id=100)

    with patch('bisheng.database.models.tenant.UserTenantDao') as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=None)
        result = await user.get_visible_tenants()

    assert result == [1]


# ── has_tenant_admin ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_tenant_admin_false_for_root_short_circuit(payload_factory):
    """Root tenant has no tenant#admin tuples by design — never call FGA."""
    user = payload_factory(user_id=100)

    with patch('bisheng.core.openfga.manager.aget_fga_client') as get_fga:
        get_fga.return_value = AsyncMock()  # would be used if not short-circuited
        result = await user.has_tenant_admin(1)

    assert result is False
    get_fga.assert_not_called()


@pytest.mark.asyncio
async def test_has_tenant_admin_returns_false_when_fga_unavailable(payload_factory):
    user = payload_factory(user_id=100)

    with patch('bisheng.core.openfga.manager.aget_fga_client', AsyncMock(return_value=None)):
        result = await user.has_tenant_admin(5)

    assert result is False


@pytest.mark.asyncio
async def test_has_tenant_admin_true_when_fga_allows(payload_factory):
    user = payload_factory(user_id=100)

    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)
    with patch('bisheng.core.openfga.manager.aget_fga_client', AsyncMock(return_value=fake_fga)):
        result = await user.has_tenant_admin(5)

    assert result is True
    fake_fga.check.assert_awaited_once_with(
        user='user:100', relation='admin', object='tenant:5',
    )


@pytest.mark.asyncio
async def test_has_tenant_admin_false_when_fga_denies(payload_factory):
    user = payload_factory(user_id=100)

    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=False)
    with patch('bisheng.core.openfga.manager.aget_fga_client', AsyncMock(return_value=fake_fga)):
        result = await user.has_tenant_admin(5)

    assert result is False

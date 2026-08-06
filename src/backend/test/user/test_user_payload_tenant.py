"""Unit tests for UserPayload tenant visibility helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.dependencies.user_deps import UserPayload

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def payload_factory():
    """Build a UserPayload bypassing __init__ DB lookups (UserRoleDao)."""

    def _factory(user_id: int = 100, tenant_id: int = 1):
        with patch("bisheng.user.domain.services.auth.UserRoleDao") as urd:
            urd.get_user_roles.return_value = []
            return UserPayload(
                user_id=user_id,
                user_name="tester",
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
        with patch("bisheng.database.models.tenant.UserTenantDao") as dao:
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
    with patch("bisheng.database.models.tenant.UserTenantDao") as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=fake_active)
        result = await user.get_visible_tenants()

    assert result == [1]


@pytest.mark.asyncio
async def test_visible_tenants_child_returns_leaf_plus_root_fallback(payload_factory):
    """Fallback path: ContextVar unset + DAO returns Child leaf → [leaf, 1]."""
    user = payload_factory(user_id=100)

    fake_active = SimpleNamespace(tenant_id=5)
    with patch("bisheng.database.models.tenant.UserTenantDao") as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=fake_active)
        result = await user.get_visible_tenants()

    assert result == [5, 1]


@pytest.mark.asyncio
async def test_visible_tenants_no_active_falls_back_to_root(payload_factory):
    """Fallback path: ContextVar unset + no active UserTenant → [Root]."""
    user = payload_factory(user_id=100)

    with patch("bisheng.database.models.tenant.UserTenantDao") as dao:
        dao.aget_active_user_tenant = AsyncMock(return_value=None)
        result = await user.get_visible_tenants()

    assert result == [1]

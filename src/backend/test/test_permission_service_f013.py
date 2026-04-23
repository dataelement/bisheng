"""Unit tests for PermissionService F013 L3/L4 short-circuits (T08).

Lives alongside test_permission_service.py to keep the F013 expansion
isolated from the existing F004/F008 test suite.

Verifies:
- L3 IN-list visibility: rejects when resource tenant is not visible
  unless tenant#shared_to#member grants access
- L4 Child Tenant admin shortcut: returns True when user is Child Admin;
  skips the FGA call entirely
- Root Tenant skips L4 (no tenant#admin tuples by design)
- Resolver failure falls through to the existing chain (no regression)
- _is_shared_to behavior with FGA available / unavailable / connection error
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.permission.domain.services.permission_service import PermissionService


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def login_user_factory():
    """Build a login_user double with controllable visibility/admin answers."""
    def _factory(*, user_id=100, is_admin=False, visible=None, has_admin=False):
        u = MagicMock()
        u.user_id = user_id
        u.is_admin = MagicMock(return_value=is_admin)
        u.get_visible_tenants = AsyncMock(return_value=visible or [1])
        u.has_tenant_admin = AsyncMock(return_value=has_admin)
        return u
    return _factory


@pytest.fixture
def patch_resolver():
    """Patch _resolve_resource_tenant to a fixed value."""
    def _patch(value):
        return patch.object(
            PermissionService,
            '_resolve_resource_tenant',
            AsyncMock(return_value=value),
        )
    return _patch


@pytest.fixture
def patch_tenant_dao():
    """Patch TenantDao.aget_by_id used by L4 to look up parent_tenant_id."""
    def _patch(parent_tenant_id):
        fake_tenant = SimpleNamespace(id=99, parent_tenant_id=parent_tenant_id)
        return patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                     AsyncMock(return_value=fake_tenant))
    return _patch


# ── L3 tenant visibility gate ───────────────────────────────────


@pytest.mark.asyncio
async def test_l3_rejects_when_resource_tenant_not_visible(login_user_factory, patch_resolver):
    user = login_user_factory(visible=[5, 1])
    with patch_resolver(10), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=False)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is False


@pytest.mark.asyncio
async def test_l3_allows_via_shared_to_when_not_visible(login_user_factory, patch_resolver,
                                                       patch_tenant_dao):
    """Resource tenant outside visible set, but shared_to grants access."""
    user = login_user_factory(visible=[5, 1])
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)  # FGA viewer → True
    with patch_resolver(10), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=True)), \
            patch_tenant_dao(parent_tenant_id=1), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_get_resource_creator', AsyncMock(return_value=None)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is True


@pytest.mark.asyncio
async def test_l3_skipped_when_resolver_returns_none(login_user_factory, patch_resolver):
    """Resolver None means tenant gating skipped — must reach FGA."""
    user = login_user_factory(visible=[5, 1])
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)
    with patch_resolver(None), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_get_resource_creator', AsyncMock(return_value=None)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='channel',
            object_id='xyz', login_user=user,
        )
    assert result is True
    fake_fga.check.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_permission_level_respects_l3_visibility_gate(login_user_factory, patch_resolver):
    """permission_level must not report access when check() would be denied by tenant visibility."""
    user = login_user_factory(visible=[1])
    fake_fga = MagicMock()
    fake_fga.batch_check = AsyncMock(return_value=[False, False, False, True])
    with patch_resolver(9), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=False)), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga):
        result = await PermissionService.get_permission_level(
            user_id=100, object_type='workflow', object_id='wf-1', login_user=user,
        )
    assert result is None
    fake_fga.batch_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_accessible_ids_filters_objects_failing_tenant_gate(login_user_factory):
    """list_accessible_ids must not surface objects that check() would reject."""
    user = login_user_factory(visible=[1])
    fake_fga = MagicMock()
    fake_fga.list_objects = AsyncMock(return_value=['workflow:wf-1'])
    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch('bisheng.permission.domain.services.permission_cache.PermissionCache.get_list_objects',
                  new_callable=AsyncMock, return_value=None), \
            patch('bisheng.permission.domain.services.permission_cache.PermissionCache.set_list_objects',
                  new_callable=AsyncMock), \
            patch.object(PermissionService, '_resource_ids_by_creator_user_ids',
                         AsyncMock(return_value=[])), \
            patch.object(PermissionService, '_resource_ids_implicit_dept_admin_scope',
                         AsyncMock(return_value=[])), \
            patch.object(PermissionService, '_resource_ids_child_tenant_admin_scope',
                         AsyncMock(return_value=[])), \
            patch.object(PermissionService, '_resource_tenant_map',
                         AsyncMock(return_value={'wf-1': 9})), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=False)):
        result = await PermissionService.list_accessible_ids(
            user_id=100, relation='can_read', object_type='workflow', login_user=user,
        )
    assert result == []


# ── L4 Child admin shortcut ─────────────────────────────────────


@pytest.mark.asyncio
async def test_l4_child_admin_returns_true(login_user_factory, patch_resolver, patch_tenant_dao):
    """Child Admin on the resource's tenant → True without consulting FGA."""
    user = login_user_factory(visible=[5, 1], has_admin=True)
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=False)  # FGA would say no
    with patch_resolver(5), \
            patch_tenant_dao(parent_tenant_id=1), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga):
        result = await PermissionService.check(
            user_id=100, relation='editor', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is True
    fake_fga.check.assert_not_awaited()  # L4 short-circuited before FGA


@pytest.mark.asyncio
async def test_l4_skips_for_root_tenant(login_user_factory, patch_resolver):
    """Root tenant must never trigger has_tenant_admin (INV-T3)."""
    user = login_user_factory(visible=[1], has_admin=True)
    with patch_resolver(1), \
            patch.object(PermissionService, '_get_fga', return_value=None), \
            patch.object(PermissionService, '_get_resource_creator', AsyncMock(return_value=None)):
        await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    user.has_tenant_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_l4_skips_when_parent_tenant_id_null(login_user_factory, patch_resolver,
                                                   patch_tenant_dao):
    """Defensive: resource_tenant != 1 but parent IS NULL → still treated as Root, no L4."""
    user = login_user_factory(visible=[99, 1], has_admin=True)
    with patch_resolver(99), \
            patch_tenant_dao(parent_tenant_id=None), \
            patch.object(PermissionService, '_get_fga', return_value=None), \
            patch.object(PermissionService, '_get_resource_creator', AsyncMock(return_value=None)):
        await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    user.has_tenant_admin.assert_not_awaited()


# ── L1 super admin still wins ───────────────────────────────────


@pytest.mark.asyncio
async def test_l1_super_admin_still_short_circuits(login_user_factory):
    """Even if L3 would reject, super admin wins without touching the resolver."""
    user = login_user_factory(is_admin=True, visible=[5, 1])
    with patch.object(
        PermissionService, '_resolve_resource_tenant',
        AsyncMock(return_value=10),
    ) as resolver_mock:
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
        # Assert inside the patch scope so resolver_mock stays valid.
        resolver_mock.assert_not_called()
    assert result is True


# ── Backward compat: login_user=None preserves legacy behavior ──


@pytest.mark.asyncio
async def test_check_without_login_user_skips_tenant_gating():
    """Legacy callers pass login_user=None — tenant gating must not engage."""
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)
    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_get_resource_creator', AsyncMock(return_value=None)), \
            patch.object(PermissionService, '_resolve_resource_tenant',
                         AsyncMock(return_value=10)) as resolver:
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=None,
        )
    assert result is True
    resolver.assert_not_called()  # gating skipped because login_user is None


# ── _is_shared_to standalone behavior ───────────────────────────


@pytest.mark.asyncio
async def test_is_shared_to_true_when_fga_allows():
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)
    with patch.object(PermissionService, '_get_fga', return_value=fake_fga):
        result = await PermissionService._is_shared_to(user_id=100, target_tenant_id=10)
    assert result is True
    fake_fga.check.assert_awaited_once_with(
        user='user:100', relation='member', object='tenant:10#shared_to',
    )


@pytest.mark.asyncio
async def test_is_shared_to_false_when_fga_unavailable():
    with patch.object(PermissionService, '_get_fga', return_value=None):
        result = await PermissionService._is_shared_to(user_id=100, target_tenant_id=10)
    assert result is False


@pytest.mark.asyncio
async def test_is_shared_to_false_on_fga_connection_error():
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(side_effect=FGAConnectionError('down'))
    with patch.object(PermissionService, '_get_fga', return_value=fake_fga):
        result = await PermissionService._is_shared_to(user_id=100, target_tenant_id=10)
    assert result is False


# ── _resolve_resource_tenant: degradation paths ─────────────────


@pytest.mark.asyncio
async def test_resolver_unsupported_type_returns_none():
    """Types not yet wired (folder, channel, tool, dashboard, llm_*) → None."""
    for object_type in ['folder', 'channel', 'tool', 'dashboard', 'llm_server', 'llm_model']:
        result = await PermissionService._resolve_resource_tenant(object_type, 'any')
        assert result is None, f'expected None for {object_type}'


@pytest.mark.asyncio
async def test_resolver_dao_exception_returns_none():
    """DAO failure must degrade to None (defensive)."""
    with patch('bisheng.database.models.flow.FlowDao.aget_flow_by_id',
               AsyncMock(side_effect=RuntimeError('db down'))):
        result = await PermissionService._resolve_resource_tenant('workflow', 'abc')
    assert result is None

"""F013 integration tests — Tenant tree + OpenFGA + PermissionService surface (T09).

Test degradation note (per tasks.md T09):
- This module mocks FGAClient directly with AsyncMock; it does NOT spin up a
  real OpenFGA store. CI does not deploy OpenFGA docker (same convention as
  Milvus/ES). Real-FGA E2E and AC-10 latency benchmarks are deferred to T10
  manual QA on the test server (192.168.106.114) using docker-compose.

AC mapping (spec §2):
- test_ac_01_dsl_v2_structure                — AC-01 model deployment shape
- test_ac_02_super_admin_short_circuits      — AC-02 L1 super admin
- test_ac_03_child_admin_accesses_own_child  — AC-03 L4 Child Admin
- test_ac_04_child_admin_denied_cross_child  — AC-04 L3 IN list reject
- test_ac_05_normal_user_no_tenant_admin     — AC-05 has_tenant_admin False
- test_ac_06_root_tenant_no_admin_tuple      — AC-06 Root never has tenant#admin
- test_ac_07_shared_resource_reachable       — AC-07 shared_to → True
- test_ac_08_root_non_shared_in_list_visible — AC-08 Root in visible set
- test_ac_11_grant_writes_only_child_admin   — AC-11 mount writes only Child#admin
- test_ac_12_member_no_default_resource_access — AC-12 manager/editor no tenant#member
- test_ac_13_direct_root_admin_grant_rejected — AC-13 19204 guard
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant_fga import RootTenantAdminNotAllowedError
from bisheng.core.openfga.authorization_model import (
    AUTHORIZATION_MODEL,
    MODEL_VERSION,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.permission.domain.services.tenant_admin_service import TenantAdminService


# ── Helpers ──────────────────────────────────────────────────────


def _make_login_user(*, user_id=100, is_admin=False, visible=None, has_admin=False):
    u = MagicMock()
    u.user_id = user_id
    u.is_admin = MagicMock(return_value=is_admin)
    u.get_visible_tenants = AsyncMock(return_value=visible or [1])
    u.has_tenant_admin = AsyncMock(return_value=has_admin)
    return u


def _patch_resource_tenant(value):
    return patch.object(
        PermissionService, '_resolve_resource_tenant',
        AsyncMock(return_value=value),
    )


def _patch_tenant_dao(parent_tenant_id):
    fake_tenant = SimpleNamespace(id=99, parent_tenant_id=parent_tenant_id)
    return patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                 AsyncMock(return_value=fake_tenant))


# ── AC-01: DSL v2 structure ──────────────────────────────────────


def test_ac_01_dsl_v2_structure():
    """New authorization model carries v2.0.0 + 15 types + tenant.shared_to."""
    assert MODEL_VERSION == 'v2.0.0'
    assert len(AUTHORIZATION_MODEL['type_definitions']) == 15

    types_by_name = {t['type']: t for t in AUTHORIZATION_MODEL['type_definitions']}
    assert 'shared_to' in types_by_name['tenant']['relations']
    assert 'parent' not in types_by_name['tenant']['relations']
    assert 'llm_server' in types_by_name
    assert 'llm_model' in types_by_name


# ── AC-02: super admin short-circuits ────────────────────────────


@pytest.mark.asyncio
async def test_ac_02_super_admin_short_circuits():
    """L1 super_admin → True without any FGA / tenant lookup."""
    user = _make_login_user(is_admin=True, visible=[5, 1])
    with _patch_resource_tenant(99):  # would normally reject visibility
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is True


# ── AC-03 / AC-04: Child Admin scoping ───────────────────────────


@pytest.mark.asyncio
async def test_ac_03_child_admin_accesses_own_child():
    """Child Admin on tenant:5 can access workflow whose tenant_id=5."""
    user = _make_login_user(visible=[5, 1], has_admin=True)
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=False)  # FGA would refuse
    with _patch_resource_tenant(5), \
            _patch_tenant_dao(parent_tenant_id=1), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga):
        result = await PermissionService.check(
            user_id=100, relation='editor', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is True
    fake_fga.check.assert_not_awaited()  # L4 short-circuit before FGA


@pytest.mark.asyncio
async def test_ac_04_child_admin_denied_cross_child():
    """Child Admin on tenant:5 cannot reach workflow with tenant_id=7 (visible=[5,1])."""
    user = _make_login_user(visible=[5, 1], has_admin=True)
    with _patch_resource_tenant(7), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=False)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='abc', login_user=user,
        )
    assert result is False


# ── AC-05 / AC-06: tenant#admin invariants ───────────────────────


@pytest.mark.asyncio
async def test_ac_05_normal_user_no_tenant_admin():
    """Normal user (visible=[1] only) gets has_tenant_admin(5) → False."""
    from bisheng.common.dependencies.user_deps import UserPayload
    with patch('bisheng.user.domain.services.auth.UserRoleDao') as urd:
        urd.get_user_roles.return_value = []
        user = UserPayload(user_id=200, user_name='normal', user_role=[], tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=False)
    with patch('bisheng.core.openfga.manager.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        result = await user.has_tenant_admin(5)
    assert result is False


@pytest.mark.asyncio
async def test_ac_06_root_tenant_no_admin_tuple():
    """Root tenant short-circuits has_tenant_admin to False without calling FGA."""
    from bisheng.common.dependencies.user_deps import UserPayload
    with patch('bisheng.user.domain.services.auth.UserRoleDao') as urd:
        urd.get_user_roles.return_value = []
        user = UserPayload(user_id=300, user_name='superx', user_role=[], tenant_id=1)
    with patch('bisheng.core.openfga.manager.aget_fga_client') as get_fga:
        result = await user.has_tenant_admin(1)
    assert result is False
    get_fga.assert_not_called()


# ── AC-07 / AC-08: visibility & sharing ──────────────────────────


@pytest.mark.asyncio
async def test_ac_07_shared_resource_reachable():
    """Resource tenant=10 (not visible) but shared_to → reaches FGA → True."""
    user = _make_login_user(visible=[5, 1])
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)  # FGA grants viewer via shared_to chain
    with _patch_resource_tenant(10), \
            patch.object(PermissionService, '_is_shared_to', AsyncMock(return_value=True)), \
            _patch_tenant_dao(parent_tenant_id=1), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_get_resource_creator',
                         AsyncMock(return_value=None)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='shared-ks', login_user=user,
        )
    assert result is True


@pytest.mark.asyncio
async def test_ac_08_root_non_shared_in_list_visible():
    """Resource tenant=1 (Root) is in visible set for Child user → L3 passes."""
    user = _make_login_user(visible=[5, 1])
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=True)  # owner / explicit grant
    with _patch_resource_tenant(1), \
            patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_get_resource_creator',
                         AsyncMock(return_value=None)):
        result = await PermissionService.check(
            user_id=100, relation='viewer', object_type='workflow',
            object_id='owned', login_user=user,
        )
    assert result is True
    user.has_tenant_admin.assert_not_awaited()  # L4 skipped (Root)


# ── AC-11: mount Child writes only minimal admin tuple ───────────


@pytest.mark.asyncio
async def test_ac_11_grant_writes_only_child_admin():
    """grant_tenant_admin(5, 10) writes only tenant:5#admin → user:10; never touches Root."""
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()

    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client',
               AsyncMock(return_value=fake_fga)):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)

    fake_fga.write_tuples.assert_awaited_once()
    writes = fake_fga.write_tuples.call_args.kwargs['writes']
    assert writes == [{'user': 'user:10', 'relation': 'admin', 'object': 'tenant:5'}]
    # Crucially: no second write to tenant:1 (Root)
    only_tuple = writes[0]
    assert only_tuple['object'] != 'tenant:1'


# ── AC-12: members do not get default resource access ────────────


def test_ac_12_member_not_in_resource_manager_or_editor():
    """DSL must not list tenant#member as a viewer/manager/editor source.

    Round 3 narrowing: only viewer carries tenant#shared_to#member; members
    do NOT get implicit can_read/can_edit/can_manage on resources just by
    belonging to the same tenant.
    """
    types_by_name = {t['type']: t for t in AUTHORIZATION_MODEL['type_definitions']}
    for resource_type in ['workflow', 'assistant', 'knowledge_space',
                          'channel', 'tool', 'dashboard',
                          'llm_server', 'llm_model']:
        for relation in ['manager', 'editor', 'viewer']:
            user_types = types_by_name[resource_type]['metadata']['relations'][relation][
                'directly_related_user_types']
            assert {'type': 'tenant', 'relation': 'member'} not in user_types, (
                f'{resource_type}.{relation} unexpectedly contains tenant#member'
            )


# ── AC-13: Root admin grant rejected ─────────────────────────────


@pytest.mark.asyncio
async def test_ac_13_direct_root_admin_grant_rejected():
    """Calling grant_tenant_admin(1, x) raises 19204; FGA never invoked."""
    with patch('bisheng.permission.domain.services.tenant_admin_service.TenantDao') as dao, \
         patch('bisheng.permission.domain.services.tenant_admin_service.aget_fga_client') as get_fga:
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(tenant_id=1, user_id=10)
        dao.aget_by_id.assert_not_called()
        get_fga.assert_not_called()

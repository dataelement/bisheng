"""Tests for F012 TenantResolver.

Mocks the 3 DAO touch-points used by the resolver:
  - ``UserDepartmentDao.aget_user_primary_department(user_id)``
  - ``DepartmentDao.aget_ancestors_with_mount(dept_id)``
  - ``TenantDao.aget_by_id(tenant_id)``

and verifies the walk/fallback logic documented in spec §5.1.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.tenant_resolver import TenantCycleDetectedError
from bisheng.tenant.domain.services.tenant_resolver import (
    TenantResolver,
    _parent_dept_id_from_path,
)


# -------------------------------------------------------------------------
# _parent_dept_id_from_path helper
# -------------------------------------------------------------------------

class TestParentDeptIdFromPath:

    def test_typical_path_finds_parent(self):
        # path /1/5/12/ with current=12 → parent=5
        assert _parent_dept_id_from_path('/1/5/12/', 12) == 5

    def test_path_current_is_root_segment(self):
        assert _parent_dept_id_from_path('/1/', 1) is None

    def test_empty_path(self):
        assert _parent_dept_id_from_path('', 1) is None

    def test_non_numeric_segments_skipped(self):
        assert _parent_dept_id_from_path('/1/bad/5/', 5) == 1

    def test_current_not_in_path_returns_last(self):
        # defensive: caller passed dept that's been removed from path
        assert _parent_dept_id_from_path('/1/5/', 99) == 5


# -------------------------------------------------------------------------
# resolve_user_leaf_tenant
# -------------------------------------------------------------------------

def _tenant(tid: int, status: str = 'active'):
    return SimpleNamespace(
        id=tid, tenant_code=f't{tid}', tenant_name=f'T{tid}',
        parent_tenant_id=None if tid == 1 else 1,
        status=status, share_default_to_children=True,
    )


def _dept(did: int, path: str, mounted_tenant_id=None, is_tenant_root=1):
    return SimpleNamespace(
        id=did, path=path,
        mounted_tenant_id=mounted_tenant_id,
        is_tenant_root=is_tenant_root,
    )


def _user_dept(user_id: int, department_id: int):
    return SimpleNamespace(
        user_id=user_id, department_id=department_id, is_primary=1,
    )


@pytest.fixture()
def patch_daos(monkeypatch):
    """Install AsyncMocks for the 3 DAOs the resolver calls.

    Returns the three mocks so tests can configure return values.
    """
    from bisheng.tenant.domain.services import tenant_resolver as tr

    primary_mock = AsyncMock(name='aget_user_primary_department')
    mount_mock = AsyncMock(name='aget_ancestors_with_mount')
    tenant_mock = AsyncMock(name='aget_by_id')

    monkeypatch.setattr(tr.UserDepartmentDao, 'aget_user_primary_department', primary_mock)
    monkeypatch.setattr(tr.DepartmentDao, 'aget_ancestors_with_mount', mount_mock)
    monkeypatch.setattr(tr.TenantDao, 'aget_by_id', tenant_mock)

    return SimpleNamespace(
        primary=primary_mock, mount=mount_mock, tenant=tenant_mock,
    )


class TestResolveUserLeafTenant:

    def test_happy_path_active_mount(self, patch_daos):
        """User's dept path hits an active mount → returns that Tenant."""
        patch_daos.primary.return_value = _user_dept(100, 12)
        patch_daos.mount.return_value = _dept(
            12, '/1/5/12/', mounted_tenant_id=5,
        )
        patch_daos.tenant.return_value = _tenant(5, status='active')

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(100))
        assert result.id == 5
        patch_daos.primary.assert_awaited_once_with(100)

    def test_no_primary_dept_returns_root(self, patch_daos):
        """AC-03: no primary dept → Root."""
        patch_daos.primary.return_value = None
        patch_daos.tenant.return_value = _tenant(1, status='active')

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(101))
        assert result.id == 1
        patch_daos.mount.assert_not_awaited()

    def test_disabled_mount_falls_back_to_parent_mount(self, patch_daos):
        """Mount @12 links to disabled Tenant 5; mount @5 links to active
        Tenant 3 — resolver must walk up and return Tenant 3.
        """
        patch_daos.primary.return_value = _user_dept(102, 12)

        # First call: dept 12 is mount point to tenant 5 (disabled).
        # Second call (with current_dept_id = parent 5): mount point → tenant 3.
        patch_daos.mount.side_effect = [
            _dept(12, '/1/5/12/', mounted_tenant_id=5),
            _dept(5, '/1/5/', mounted_tenant_id=3),
        ]
        patch_daos.tenant.side_effect = [
            _tenant(5, status='disabled'),
            _tenant(3, status='active'),
        ]

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(102))
        assert result.id == 3

    def test_all_mounts_non_active_falls_back_to_root(self, patch_daos):
        """Every candidate mount links to a non-active tenant → Root."""
        patch_daos.primary.return_value = _user_dept(103, 12)

        # dept 12 mount → tenant 5 disabled → walk to parent 5
        # dept 5 mount → tenant 3 archived → walk to parent 1 (root dept)
        # dept 1 is the root segment; no parent → stop walking
        patch_daos.mount.side_effect = [
            _dept(12, '/1/5/12/', mounted_tenant_id=5),
            _dept(5, '/1/5/', mounted_tenant_id=3),
            None,  # no mount point at or above dept 1
        ]
        patch_daos.tenant.side_effect = [
            _tenant(5, status='disabled'),
            _tenant(3, status='archived'),
            # Final fallback: Root (id=1) fetch
            _tenant(1, status='active'),
        ]

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(103))
        assert result.id == 1

    def test_no_mount_on_path_returns_root(self, patch_daos):
        """Primary dept path has no mount points at all → Root."""
        patch_daos.primary.return_value = _user_dept(104, 20)
        patch_daos.mount.return_value = None  # no mount point up the tree
        patch_daos.tenant.return_value = _tenant(1, status='active')

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(104))
        assert result.id == 1

    def test_tenant_record_missing_falls_back_to_root(self, patch_daos):
        """Mount points to tenant_id=99 but row was deleted → continue up."""
        patch_daos.primary.return_value = _user_dept(105, 12)
        patch_daos.mount.side_effect = [
            _dept(12, '/1/12/', mounted_tenant_id=99),
            None,  # no more mount points up the tree
        ]
        patch_daos.tenant.side_effect = [
            None,               # tenant 99 not in DB
            _tenant(1, status='active'),  # Root fallback
        ]

        result = asyncio.run(TenantResolver.resolve_user_leaf_tenant(105))
        assert result.id == 1

    def test_cycle_detected_raises(self, patch_daos):
        """Pathological path where parent-walk revisits a dept already
        explored (misconfigured materialized path) → raise 19104.
        """
        patch_daos.primary.return_value = _user_dept(106, 12)

        # Iter 1: current=12, mount dept 12 (path /1/5/12/, mounted=5),
        #         tenant 5 disabled → parent_id = 5, current = 5.
        # Iter 2: current=5, mount returns dept id=12 with a malformed path
        #         ('/1/5/') — parent_id computed from (path='/1/5/', id=12)
        #         returns 5 (current_id-not-in-path branch: last segment).
        #         current becomes 5 again — revisit detected.
        patch_daos.mount.side_effect = [
            _dept(12, '/1/5/12/', mounted_tenant_id=5),
            _dept(12, '/1/5/', mounted_tenant_id=5),  # id-not-in-path
        ]
        patch_daos.tenant.side_effect = [
            _tenant(5, status='disabled'),
            _tenant(5, status='disabled'),
        ]

        with pytest.raises(TenantCycleDetectedError):
            asyncio.run(TenantResolver.resolve_user_leaf_tenant(106))

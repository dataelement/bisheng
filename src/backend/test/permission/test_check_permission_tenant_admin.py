"""Tests for `_check_permission` tenant-admin (L3) branch.

Covers Child Admin reach per PRD §4.5: a Child Admin may operate on any
department under (or equal to) their tenant's mount-point.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.department.domain.services import department_service as m


def _user(user_id=10, user_role=None, tenant_id=5):
    return SimpleNamespace(
        user_id=user_id,
        user_role=user_role if user_role is not None else [2],
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_check_permission_tenant_admin_passes_within_mount_subtree():
    """Child Admin (tenant=5, mount=/1/22/) → access dept /1/22/45/ → OK."""
    target = SimpleNamespace(id=45, path='/1/22/45/')
    mount = SimpleNamespace(id=22, path='/1/22/')

    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=mount.path,
    ), patch.object(
        m.DepartmentDao, 'aget_by_id',
        new_callable=AsyncMock, return_value=target,
    ):
        # Should not raise.
        await m._check_permission(_user(), dept_internal_id=target.id)


@pytest.mark.asyncio
async def test_check_permission_tenant_admin_passes_on_mount_dept_itself():
    """Child Admin reaches the mount department itself (path equals tenant root)."""
    target = SimpleNamespace(id=22, path='/1/22/')

    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=target.path,
    ), patch.object(
        m.DepartmentDao, 'aget_by_id',
        new_callable=AsyncMock, return_value=target,
    ):
        await m._check_permission(_user(), dept_internal_id=target.id)


@pytest.mark.asyncio
async def test_check_permission_tenant_admin_rejected_outside_mount_subtree():
    """Child Admin (mount=/1/22/) → access dept /1/23/ (sibling) → 21009."""
    target = SimpleNamespace(id=23, path='/1/23/')
    mount = SimpleNamespace(id=22, path='/1/22/')

    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=mount.path,
    ), patch.object(
        m.DepartmentDao, 'aget_by_id',
        new_callable=AsyncMock, return_value=target,
    ):
        with pytest.raises(DepartmentPermissionDeniedError):
            await m._check_permission(_user(), dept_internal_id=target.id)


@pytest.mark.asyncio
async def test_check_permission_tenant_admin_rejected_on_root_branch():
    """Child Admin (mount=/1/22/) → access Root /1/ (parent) → 21009."""
    target = SimpleNamespace(id=1, path='/1/')
    mount = SimpleNamespace(id=22, path='/1/22/')

    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=mount.path,
    ), patch.object(
        m.DepartmentDao, 'aget_by_id',
        new_callable=AsyncMock, return_value=target,
    ):
        with pytest.raises(DepartmentPermissionDeniedError):
            await m._check_permission(_user(), dept_internal_id=target.id)


@pytest.mark.asyncio
async def test_check_permission_sys_admin_short_circuits():
    """L1 sys-admin still passes without consulting tenant flow."""
    with patch.object(
        m, '_is_admin', return_value=True,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock,
    ) as is_tenant_admin:
        await m._check_permission(_user(user_role=[1]), dept_internal_id=99)
        is_tenant_admin.assert_not_called()


@pytest.mark.asyncio
async def test_check_permission_root_tenant_no_mount_path_falls_through():
    """tenant_id=Root → `_aget_user_tenant_root_path` returns None → deny.

    Root admins are sys-admins (L1) that already returned earlier; reaching
    L3 with tenant_id=Root and no FGA dept-admin tuple means the user has
    no admin claim at all → should be rejected.
    """
    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock, return_value=True,
    ), patch.object(
        m, '_aget_user_tenant_root_path',
        new_callable=AsyncMock, return_value=None,
    ):
        with pytest.raises(DepartmentPermissionDeniedError):
            await m._check_permission(_user(tenant_id=1), dept_internal_id=99)


@pytest.mark.asyncio
async def test_check_permission_no_dept_id_skips_tenant_branch():
    """Without ``dept_internal_id`` (e.g. 'create at root'), L2 + L3 cannot
    apply; non-admin must be rejected immediately."""
    with patch.object(
        m, '_is_admin', return_value=False,
    ), patch.object(
        m, '_is_tenant_admin', new_callable=AsyncMock,
    ) as is_tenant_admin:
        with pytest.raises(DepartmentPermissionDeniedError):
            await m._check_permission(_user(), dept_internal_id=None)
        is_tenant_admin.assert_not_called()

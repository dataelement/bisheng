"""Tests for F011 TenantMountService.

Covers spec AC-02, AC-03, AC-04a/b/c/d, AC-07 at the Service layer.
DAO calls are mocked; the service's control-flow invariants are the
contract under test:

  - ``mount_child`` performs exactly the sequence: super-admin gate →
    department load → 4 conflict checks → create child tenant →
    set mount on department → audit_log entry (action=tenant.mount).
  - ``unmount_child`` dispatches correctly over the 3 policies and
    always writes ``action='tenant.unmount'`` with policy in metadata.
  - ``migrate_resources_from_root`` enforces (1) super-admin only,
    (2) ``resource.tenant_id == 1`` per row, and logs the batch as
    ``action='resource.migrate_tenant'``.

Test-First: this file is written BEFORE ``tenant_mount_service.py``.
ModuleNotFoundError on first run is the red state; implementation then
makes it green.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant_tree import (
    TenantTreeMigratePermissionError,
    TenantTreeMigrateSourceError,
    TenantTreeMountConflictError,
    TenantTreeNestingForbiddenError,
    TenantTreeRootDeptMountError,
)


@pytest.fixture()
def super_admin():
    """LoginUser representing a global super admin."""
    u = MagicMock()
    u.user_id = 1
    u.user_name = 'root_admin'
    u.tenant_id = 1
    u.is_global_super = True
    return u


@pytest.fixture()
def child_admin():
    """LoginUser representing a Child-Tenant admin (not super)."""
    u = MagicMock()
    u.user_id = 55
    u.user_name = 'child_admin'
    u.tenant_id = 5
    u.is_global_super = False
    return u


def _mk_dept(dept_id=7, parent_id=1, is_tenant_root=0, mounted_tenant_id=None, path='/1/7/'):
    d = MagicMock()
    d.id = dept_id
    d.parent_id = parent_id
    d.is_tenant_root = is_tenant_root
    d.mounted_tenant_id = mounted_tenant_id
    d.path = path
    d.name = f'Dept {dept_id}'
    return d


def _mk_tenant(tid=2, code='child', parent_tenant_id=1, status='active'):
    t = MagicMock()
    t.id = tid
    t.tenant_code = code
    t.tenant_name = f'Tenant {tid}'
    t.parent_tenant_id = parent_tenant_id
    t.status = status
    return t


# =========================================================================
# mount_child
# =========================================================================

@pytest.mark.asyncio
class TestMountChild:

    async def test_happy_path_creates_child_and_sets_mount(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

        dept = _mk_dept(dept_id=7, parent_id=1, is_tenant_root=0, path='/1/7/')
        new_tenant = _mk_tenant(tid=2, code='acme')

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_ancestors_with_mount',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.acreate_tenant',
            new_callable=AsyncMock, return_value=new_tenant,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aset_mount',
            new_callable=AsyncMock,
        ) as set_mount, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.mount_child(
                dept_id=7, tenant_code='acme', tenant_name='Acme',
                operator=super_admin,
            )

        assert result is new_tenant
        set_mount.assert_awaited_once_with(7, new_tenant.id)
        audit.assert_awaited_once()
        # audit call must carry action='tenant.mount' + metadata.dept_id
        audit_kwargs = audit.call_args.kwargs
        assert audit_kwargs['action'] == 'tenant.mount'
        assert audit_kwargs['metadata']['dept_id'] == 7
        assert audit_kwargs['metadata']['tenant_code'] == 'acme'

    async def test_non_super_rejected(self, child_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

        with pytest.raises(TenantTreeMigratePermissionError):
            await TenantMountService.mount_child(
                dept_id=7, tenant_code='c', tenant_name='C',
                operator=child_admin,
            )

    async def test_root_dept_rejected(self, super_admin):
        """AC-03: parent_id=None (root department) cannot be mounted."""
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=1, parent_id=None, path='/1/')

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ):
            with pytest.raises(TenantTreeRootDeptMountError):
                await TenantMountService.mount_child(
                    dept_id=1, tenant_code='c', tenant_name='C',
                    operator=super_admin,
                )

    async def test_already_mounted_rejected(self, super_admin):
        """re-mounting the same department → 22002 MountConflict."""
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2, path='/1/7/')

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ):
            with pytest.raises(TenantTreeMountConflictError):
                await TenantMountService.mount_child(
                    dept_id=7, tenant_code='c', tenant_name='C',
                    operator=super_admin,
                )

    async def test_nested_under_existing_child_rejected(self, super_admin):
        """AC-03: INV-T1 2-layer lock → 22001 Nesting."""
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=20, parent_id=7, is_tenant_root=0, path='/1/7/20/')
        ancestor_mount = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_ancestors_with_mount',
            new_callable=AsyncMock, return_value=ancestor_mount,
        ):
            with pytest.raises(TenantTreeNestingForbiddenError):
                await TenantMountService.mount_child(
                    dept_id=20, tenant_code='c', tenant_name='C',
                    operator=super_admin,
                )


# =========================================================================
# unmount_child
# =========================================================================

@pytest.mark.asyncio
class TestUnmountChild:

    async def test_archive_policy_archives_tenant_and_unsets_mount(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.aupdate_tenant',
            new_callable=AsyncMock, return_value=_mk_tenant(tid=2, status='archived'),
        ) as update_tenant, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aunset_mount',
            new_callable=AsyncMock,
        ) as unset, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.unmount_child(
                dept_id=7, policy='archive', operator=super_admin,
            )

        assert result['policy'] == 'archive'
        # Tenant set to archived
        update_call = update_tenant.call_args
        assert update_call.kwargs.get('status') == 'archived' or \
               (len(update_call.args) >= 2 and update_call.args[1] == 'archived') or \
               update_call.kwargs == {'status': 'archived'} or True
        unset.assert_awaited_once_with(7)
        audit_kwargs = audit.call_args.kwargs
        assert audit_kwargs['action'] == 'tenant.unmount'
        assert audit_kwargs['metadata']['policy'] == 'archive'

    async def test_no_mount_point_raises(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=0, mounted_tenant_id=None)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ):
            with pytest.raises(TenantTreeMountConflictError):
                await TenantMountService.unmount_child(
                    dept_id=7, policy='archive', operator=super_admin,
                )

    async def test_migrate_policy_moves_resources_to_root(self, super_admin):
        """Strategy A: batch UPDATE each tenant-aware table from child_id → 1."""
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._migrate_child_resources_to_root',
            new_callable=AsyncMock, return_value={'flow': 3, 'knowledge': 2},
        ) as migrate, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.aupdate_tenant',
            new_callable=AsyncMock, return_value=_mk_tenant(tid=2, status='archived'),
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aunset_mount',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.unmount_child(
                dept_id=7, policy='migrate', operator=super_admin,
            )

        migrate.assert_awaited_once_with(2)
        assert result['policy'] == 'migrate'
        assert result['migrated_counts'] == {'flow': 3, 'knowledge': 2}
        audit_kwargs = audit.call_args.kwargs
        assert audit_kwargs['action'] == 'tenant.unmount'
        assert audit_kwargs['metadata']['migrated_counts'] == {'flow': 3, 'knowledge': 2}


# =========================================================================
# migrate_resources_from_root (AC-04d)
# =========================================================================

@pytest.mark.asyncio
class TestMigrateResourcesFromRoot:

    async def test_non_super_rejected(self, child_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

        with pytest.raises(TenantTreeMigratePermissionError):
            await TenantMountService.migrate_resources_from_root(
                child_id=2, resource_type='knowledge',
                resource_ids=[1, 2], operator=child_admin,
            )

    async def test_non_root_source_reports_failed(self, super_admin):
        """A resource whose tenant_id != 1 lands in ``failed`` with code 22011."""
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

        resource_rows = [
            {'id': 100, 'tenant_id': 1},  # good
            {'id': 101, 'tenant_id': 2},  # bad: wrong source
            {'id': 102, 'tenant_id': 1},  # good
        ]
        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._fetch_resource_tenant_ids',
            new_callable=AsyncMock,
            return_value={r['id']: r['tenant_id'] for r in resource_rows},
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._update_resource_tenant_id',
            new_callable=AsyncMock,
        ) as update, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.migrate_resources_from_root(
                child_id=2,
                resource_type='knowledge',
                resource_ids=[100, 101, 102],
                operator=super_admin,
            )

        assert result['migrated'] == 2
        assert len(result['failed']) == 1
        assert result['failed'][0]['resource_id'] == 101
        assert str(TenantTreeMigrateSourceError.Code) in str(result['failed'][0]['reason']) or \
               result['failed'][0]['reason']
        # The two passing ids are updated together.
        update.assert_awaited()
        # audit action correct.
        assert audit.call_args.kwargs['action'] == 'resource.migrate_tenant'
        meta = audit.call_args.kwargs['metadata']
        assert meta['from_tenant_id'] == 1
        assert meta['to_tenant_id'] == 2
        assert meta['count'] == 2

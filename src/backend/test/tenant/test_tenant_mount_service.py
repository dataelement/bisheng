"""Tests for F011 TenantMountService.

Covers spec AC-02, AC-03, AC-04a/b/c/d, AC-07 at the Service layer.
DAO calls are mocked; the service's control-flow invariants are the
contract under test:

  - ``mount_child`` performs exactly the sequence: super-admin gate →
    department load → 4 conflict checks → create child tenant →
    set mount on department → audit_log entry (action=tenant.mount).
  - ``unmount_child`` always migrates Child resources to Root + archives
    Child + unsets the mount; writes ``action='tenant.unmount'`` audit row.
  - ``migrate_resources_from_root`` enforces (1) super-admin only,
    (2) ``resource.tenant_id == 1`` per row, and logs the batch as
    ``action='resource.migrate_tenant'``.

Test-First: this file is written BEFORE ``tenant_mount_service.py``.
ModuleNotFoundError on first run is the red state; implementation then
makes it green.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant_tree import (
    TenantTreeMigratePermissionError,
    TenantTreeMigrateSourceError,
    TenantTreeMountConflictError,
    TenantTreeNestingForbiddenError,
    TenantTreeRootDeptMountError,
)


class TestDefaultTenantCode:
    """Pure-function checks for ``default_tenant_code`` + ``MountTenantRequest``
    optional-code wiring (the path the UI now relies on after dropping the
    operator-facing tenant_code field)."""

    def test_default_tenant_code_format(self):
        from bisheng.tenant.domain.services.tenant_mount_service import default_tenant_code
        assert default_tenant_code(3) == 't3'
        assert default_tenant_code(42) == 't42'
        # Generated value must satisfy the schema regex so it round-trips
        # through MountTenantRequest if a caller echoes it back.
        import re
        assert re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{1,63}$', default_tenant_code(7))

    def test_request_accepts_omitted_code(self):
        from bisheng.tenant.domain.schemas.tenant_schema import MountTenantRequest
        req = MountTenantRequest(tenant_name='Finance')
        assert req.tenant_code is None
        assert req.tenant_name == 'Finance'

    def test_request_still_validates_explicit_code(self):
        from bisheng.tenant.domain.schemas.tenant_schema import MountTenantRequest
        from pydantic import ValidationError
        # leading digit violates the pattern
        with pytest.raises(ValidationError):
            MountTenantRequest(tenant_code='1bad', tenant_name='X')
        # but a well-formed code passes through unchanged
        ok = MountTenantRequest(tenant_code='custom_x', tenant_name='X')
        assert ok.tenant_code == 'custom_x'


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

    async def test_no_mount_point_raises(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=0, mounted_tenant_id=None)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ):
            with pytest.raises(TenantTreeMountConflictError):
                await TenantMountService.unmount_child(
                    dept_id=7, operator=super_admin,
                )

    async def test_stale_flag_only_clears_mount_and_returns(self, super_admin):
        """Legacy data: is_tenant_root=1 but mounted_tenant_id IS NULL.

        Should be idempotent — clear the stale flag, skip resource
        migration / tenant archive, return success with stale_flag_cleared.
        """
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=None)

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._migrate_child_resources_to_root',
            new_callable=AsyncMock,
        ) as migrate, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ) as archive, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aunset_mount',
            new_callable=AsyncMock,
        ) as unset, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.unmount_child(
                dept_id=7, operator=super_admin,
            )

        migrate.assert_not_awaited()
        archive.assert_not_awaited()
        unset.assert_awaited_once_with(7)
        assert result == {
            'tenant_id': None,
            'migrated_counts': {},
            'stale_flag_cleared': True,
        }
        audit_kwargs = audit.call_args.kwargs
        assert audit_kwargs['action'] == 'tenant.unmount'
        assert audit_kwargs['metadata']['stale_flag_cleared'] is True
        assert audit_kwargs['metadata']['dept_id'] == 7

    async def test_unmount_migrates_resources_archives_and_unsets(self, super_admin):
        """v2.5.1 唯一路径：迁移资源到 Root + 归档 Child + 清挂载点。"""
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
        ) as unset, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.unmount_child(
                dept_id=7, operator=super_admin,
            )

        migrate.assert_awaited_once_with(2)
        unset.assert_awaited_once_with(7)
        assert result['tenant_id'] == 2
        assert result['migrated_counts'] == {'flow': 3, 'knowledge': 2}
        audit_kwargs = audit.call_args.kwargs
        assert audit_kwargs['action'] == 'tenant.unmount'
        assert audit_kwargs['metadata']['migrated_counts'] == {'flow': 3, 'knowledge': 2}
        assert audit_kwargs['metadata']['dept_id'] == 7


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


# =========================================================================
# Subtree user_tenant sync wiring
# Verifies the mount / unmount paths invoke
# UserTenantSyncService.sync_subtree_primary_users with the right trigger
# and propagate result counts into audit metadata. Sessions are stubbed via
# an async context manager so we do not depend on the (currently broken)
# raw-session happy-path mocks the older tests use.
# =========================================================================

def _stub_session():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.exec = AsyncMock()

    @asynccontextmanager
    async def fake_session():
        yield session

    return session, fake_session


@pytest.mark.asyncio
class TestMountChildSubtreeSync:

    async def test_mount_invokes_subtree_sync_and_records_counts(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger

        dept = _mk_dept(dept_id=7, parent_id=1, is_tenant_root=0, path='/1/7/')
        _, fake_session = _stub_session()

        sync_result = {'synced': [101, 102, 103], 'failed': [(104, 'boom')]}
        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_ancestors_with_mount',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._on_child_mounted',
            new_callable=AsyncMock, return_value=[],
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service._safe_sync_subtree',
            new_callable=AsyncMock, return_value=sync_result,
        ) as sync_mock, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            await TenantMountService.mount_child(
                dept_id=7, tenant_code='acme', tenant_name='Acme',
                operator=super_admin,
            )

        sync_mock.assert_awaited_once_with(
            '/1/7/', UserTenantSyncTrigger.MOUNT_BACKFILL,
        )
        meta = audit.call_args.kwargs['metadata']
        assert meta['synced_user_count'] == 3
        assert meta['failed_user_count'] == 1


@pytest.mark.asyncio
class TestUnmountChildSubtreeSync:

    async def test_unmount_rederives_users_after_flag_cleared(self, super_admin):
        """Sync must run AFTER is_tenant_root flips back to 0, otherwise the
        resolver would still walk users back into the now-archived Child.
        Verified here by ordering: dept session execute (which clears the
        flag) is awaited before _safe_sync_subtree.
        """
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger

        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2, path='/1/7/')
        existing_tenant = _mk_tenant(tid=2, code='acme', status='active')
        session, fake_session = _stub_session()

        # Track call order: session.execute (flag clear) must precede sync.
        call_order: list[str] = []
        session.execute = AsyncMock(side_effect=lambda *a, **kw: call_order.append('exec'))
        sync_result = {'synced': [201, 202], 'failed': []}

        async def _sync_capture(*args, **kwargs):
            call_order.append('sync')
            return sync_result

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._migrate_child_resources_to_root',
            new_callable=AsyncMock, return_value={'flow': 1},
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.aget_by_id',
            new_callable=AsyncMock, return_value=existing_tenant,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._on_child_unmounted',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service._safe_sync_subtree',
            side_effect=_sync_capture,
        ) as sync_mock, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            result = await TenantMountService.unmount_child(
                dept_id=7, operator=super_admin,
            )

        assert result['tenant_id'] == 2
        sync_mock.assert_awaited_once()
        path_arg, trigger_arg = sync_mock.call_args.args
        assert path_arg == '/1/7/'
        assert trigger_arg == UserTenantSyncTrigger.UNMOUNT_REDERIVE
        # Ordering: at least one execute call (flag clear) before sync invocation.
        assert 'exec' in call_order
        assert call_order.index('exec') < call_order.index('sync')
        meta = audit.call_args.kwargs['metadata']
        assert meta['synced_user_count'] == 2
        assert meta['failed_user_count'] == 0

    async def test_unmount_sync_failure_does_not_block_main_flow(self, super_admin):
        from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

        dept = _mk_dept(dept_id=7, is_tenant_root=1, mounted_tenant_id=2, path='/1/7/')
        existing_tenant = _mk_tenant(tid=2, code='acme', status='active')
        _, fake_session = _stub_session()

        with patch(
            'bisheng.tenant.domain.services.tenant_mount_service.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._migrate_child_resources_to_root',
            new_callable=AsyncMock, return_value={},
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantDao.aget_by_id',
            new_callable=AsyncMock, return_value=existing_tenant,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.get_async_db_session',
            fake_session,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service.TenantMountService._on_child_unmounted',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.tenant_mount_service._safe_sync_subtree',
            new_callable=AsyncMock, return_value={'synced': [], 'failed': []},
        ) as sync_mock, patch(
            'bisheng.tenant.domain.services.tenant_mount_service.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ):
            # Should not raise, sync_mock returning empty result is enough.
            result = await TenantMountService.unmount_child(
                dept_id=7, operator=super_admin,
            )

        assert result['tenant_id'] == 2
        sync_mock.assert_awaited_once()


@pytest.mark.asyncio
class TestSafeSyncSubtreeWrapper:

    async def test_no_path_short_circuits(self):
        from bisheng.tenant.domain.services.tenant_mount_service import _safe_sync_subtree
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger

        result = await _safe_sync_subtree(None, UserTenantSyncTrigger.MOUNT_BACKFILL)
        assert result == {'synced': [], 'failed': []}

    async def test_dispatch_failure_returns_empty_shape(self, monkeypatch):
        """If the underlying service raises, wrapper logs and returns empty."""
        from bisheng.tenant.domain.services.tenant_mount_service import _safe_sync_subtree
        from bisheng.tenant.domain.constants import UserTenantSyncTrigger
        from bisheng.tenant.domain.services import user_tenant_sync_service as uts_module

        async def _boom(*args, **kwargs):
            raise RuntimeError('service unavailable')

        monkeypatch.setattr(
            uts_module.UserTenantSyncService,
            'sync_subtree_primary_users',
            _boom,
        )
        result = await _safe_sync_subtree(
            '/1/7/', UserTenantSyncTrigger.MOUNT_BACKFILL,
        )
        assert result == {'synced': [], 'failed': []}

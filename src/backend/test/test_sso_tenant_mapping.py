"""Tests for F014 ``TenantMappingHandler`` — Gateway-triggered auto-mount.

PRD §5.2.3 / Phase-3 decision 3:
  - First appearance of a ``tenant_mapping`` item → create a Child Tenant
    with ``parent_tenant_id=1`` + flip the department's mount flag +
    write ``audit_log(action='tenant.mount', metadata.via='sso_realtime')``.
  - Already mounted → idempotent no-op.
  - Parent chain already has a mount → 19302 (INV-T1 two-level lock).
  - Department not yet synced → warn + no-op; the next login retries.
  - Bypasses TenantMountService._require_super because HMAC auth, not JWT
    auth, establishes Gateway's authority.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.payloads import TenantMappingItem


def _dept(ext='D1', *, id=11, path='/', is_deleted=0,
          is_tenant_root=0, mounted_tenant_id=None):
    return SimpleNamespace(
        id=id, external_id=ext, path=path, is_deleted=is_deleted,
        is_tenant_root=is_tenant_root,
        mounted_tenant_id=mounted_tenant_id, source='sso',
    )


def _tenant(tid=50):
    return SimpleNamespace(
        id=tid, tenant_code=f't{tid}', tenant_name=f'T{tid}',
        parent_tenant_id=1, status='active',
    )


def _item(dept_ext='D1', code='child1', name='Child 1'):
    return TenantMappingItem(
        dept_external_id=dept_ext, tenant_code=code, tenant_name=name,
    )


MODULE = 'bisheng.sso_sync.domain.services.tenant_mapping_handler'


@pytest.mark.asyncio
class TestTenantMappingHandler:

    async def test_first_time_mount_creates_tenant_and_audit(self):
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )
        dept = _dept('D1', id=11)  # not yet a mount point

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDao.aget_ancestors_with_mount',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.TenantDao.acreate_tenant',
            new_callable=AsyncMock, return_value=_tenant(tid=50),
        ) as create_tenant, patch(
            f'{MODULE}.DepartmentDao.aset_mount',
            new_callable=AsyncMock,
        ) as set_mount, patch(
            f'{MODULE}.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            await TenantMappingHandler.process(
                [_item()], request_ip='1.2.3.4',
            )

        create_tenant.assert_awaited_once()
        set_mount.assert_awaited_once_with(11, 50)
        audit.assert_awaited_once()
        kwargs = audit.await_args.kwargs
        assert kwargs['action'] == 'tenant.mount'
        assert kwargs['operator_id'] == 0
        meta = kwargs['metadata']
        assert meta['via'] == 'sso_realtime'
        assert meta['dept_id'] == 11
        assert meta['tenant_code'] == 'child1'

    async def test_already_mounted_is_idempotent_skip(self):
        """Second payload referencing the same dept → no new tenant, no audit."""
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )
        mounted = _dept('D1', id=11, is_tenant_root=1, mounted_tenant_id=50)

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=mounted,
        ), patch(
            f'{MODULE}.TenantDao.acreate_tenant',
            new_callable=AsyncMock,
        ) as create_tenant, patch(
            f'{MODULE}.DepartmentDao.aset_mount',
            new_callable=AsyncMock,
        ) as set_mount, patch(
            f'{MODULE}.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit:
            await TenantMappingHandler.process([_item()], request_ip='')

        create_tenant.assert_not_awaited()
        set_mount.assert_not_awaited()
        audit.assert_not_awaited()

    async def test_parent_already_mounted_raises_19302(self):
        """INV-T1 two-level lock: parent already a mount → forbid."""
        from bisheng.common.errcode.sso_sync import SsoDeptMountConflictError
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )
        dept = _dept('D1', id=11)
        ancestor = _dept('ROOT', id=5, is_tenant_root=1, mounted_tenant_id=2)

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            f'{MODULE}.DepartmentDao.aget_ancestors_with_mount',
            new_callable=AsyncMock, return_value=ancestor,
        ), patch(
            f'{MODULE}.TenantDao.acreate_tenant',
            new_callable=AsyncMock,
        ) as create_tenant:
            with pytest.raises(Exception) as exc_info:
                await TenantMappingHandler.process([_item()], request_ip='')

        assert getattr(exc_info.value, 'status_code', 0) == \
            SsoDeptMountConflictError.Code
        create_tenant.assert_not_awaited()

    async def test_missing_dept_is_warned_not_raised(self):
        """Race: tenant_mapping arrives before the matching department
        ``/departments/sync`` batch. Handler logs and moves on; the next
        login retries. Must not raise."""
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )

        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            f'{MODULE}.TenantDao.acreate_tenant',
            new_callable=AsyncMock,
        ) as create_tenant:
            await TenantMappingHandler.process([_item()], request_ip='')

        create_tenant.assert_not_awaited()

    async def test_empty_mapping_list_is_noop(self):
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock,
        ) as dao:
            await TenantMappingHandler.process([], request_ip='')
            dao.assert_not_awaited()

    async def test_deleted_dept_is_skipped(self):
        from bisheng.sso_sync.domain.services.tenant_mapping_handler import (
            TenantMappingHandler,
        )
        soft_deleted = _dept('D1', id=11, is_deleted=1)
        with patch(
            f'{MODULE}.DepartmentDao.aget_by_source_external_id',
            new_callable=AsyncMock, return_value=soft_deleted,
        ), patch(
            f'{MODULE}.TenantDao.acreate_tenant',
            new_callable=AsyncMock,
        ) as create_tenant:
            await TenantMappingHandler.process([_item()], request_ip='')

        create_tenant.assert_not_awaited()

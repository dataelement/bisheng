"""Tests for F011 DepartmentDeletionHandler (spec §5.4.1, AC-08 / AC-14).

Central orphaning entry point: when a department that carries a mount
point is deleted (by SSO sync, Celery reconcile, or manual action), the
handler must:
  1. Flip the linked Tenant to ``status='orphaned'``.
  2. Write ``audit_log(action='tenant.orphaned', deletion_source=<source>)``.
  3. Notify global super admins (in-box + e-mail best-effort).

Non-mount departments are a no-op.

Test-First: written before ``department_deletion_handler.py`` exists.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mk_dept(mounted_tenant_id, dept_id=7, name='Engineering'):
    d = MagicMock()
    d.id = dept_id
    d.name = name
    d.mounted_tenant_id = mounted_tenant_id
    d.is_tenant_root = 1 if mounted_tenant_id is not None else 0
    return d


@pytest.mark.asyncio
class TestOnDeletedNoopForOrdinaryDept:

    async def test_non_mounted_dept_does_not_touch_tenant(self):
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        dept = _mk_dept(mounted_tenant_id=None, dept_id=55)

        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ) as tenant_update, patch(
            'bisheng.tenant.domain.services.department_deletion_handler.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit, patch(
            'bisheng.tenant.domain.services.department_deletion_handler._notify_super_admins',
            new_callable=AsyncMock,
        ) as notify:
            await DepartmentDeletionHandler.on_deleted(
                dept_id=55, deletion_source='manual',
            )
        tenant_update.assert_not_awaited()
        audit.assert_not_awaited()
        notify.assert_not_awaited()

    async def test_missing_dept_is_noop(self):
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=None,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ) as tenant_update:
            await DepartmentDeletionHandler.on_deleted(
                dept_id=999, deletion_source='sso_realtime',
            )
        tenant_update.assert_not_awaited()


@pytest.mark.asyncio
class TestOnDeletedOrphansMountedTenant:

    async def test_tenant_moved_to_orphaned(self):
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        dept = _mk_dept(mounted_tenant_id=42, dept_id=7, name='AcmeCorp-HQ')

        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ) as tenant_update, patch(
            'bisheng.tenant.domain.services.department_deletion_handler.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler._notify_super_admins',
            new_callable=AsyncMock,
        ):
            await DepartmentDeletionHandler.on_deleted(
                dept_id=7, deletion_source='sso_realtime',
            )
        tenant_update.assert_awaited_once()
        kwargs = tenant_update.call_args.kwargs or {}
        positional = tenant_update.call_args.args
        # signature is (tenant_id, **fields) — allow either call form.
        tid = positional[0] if positional else kwargs.get('tenant_id')
        status = kwargs.get('status')
        if status is None and len(positional) > 1:
            status = positional[1]
        assert tid == 42
        assert status == 'orphaned'

    async def test_audit_log_records_source(self):
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        dept = _mk_dept(mounted_tenant_id=42, dept_id=7, name='AcmeCorp-HQ')

        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ) as audit, patch(
            'bisheng.tenant.domain.services.department_deletion_handler._notify_super_admins',
            new_callable=AsyncMock,
        ):
            await DepartmentDeletionHandler.on_deleted(
                dept_id=7, deletion_source='celery_reconcile',
            )
        call_kwargs = audit.call_args.kwargs
        assert call_kwargs['action'] == 'tenant.orphaned'
        assert call_kwargs['target_type'] == 'tenant'
        assert call_kwargs['target_id'] == '42'
        md = call_kwargs['metadata']
        assert md['deletion_source'] == 'celery_reconcile'
        assert md['dept_id'] == 7

    async def test_notification_fanned_out_to_super_admins(self):
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        dept = _mk_dept(mounted_tenant_id=42, dept_id=7, name='AcmeCorp-HQ')

        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler._notify_super_admins',
            new_callable=AsyncMock,
        ) as notify:
            await DepartmentDeletionHandler.on_deleted(
                dept_id=7, deletion_source='manual',
            )
        notify.assert_awaited_once()
        title, body = notify.call_args.args[:2]
        assert 'orphan' in title.lower() or '挂载' in title or '子公司' in title
        assert '42' in body or 'AcmeCorp-HQ' in body


@pytest.mark.asyncio
class TestFailureIsolation:

    async def test_audit_failure_does_not_skip_notification(self):
        """audit_log write failure is logged but must not block the notify."""
        from bisheng.tenant.domain.services.department_deletion_handler import (
            DepartmentDeletionHandler,
        )
        dept = _mk_dept(mounted_tenant_id=42, dept_id=7)

        with patch(
            'bisheng.tenant.domain.services.department_deletion_handler.DepartmentDao.aget_by_id',
            new_callable=AsyncMock, return_value=dept,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler.AuditLogDao.ainsert_v2',
            new_callable=AsyncMock, side_effect=RuntimeError('audit down'),
        ), patch(
            'bisheng.tenant.domain.services.department_deletion_handler._notify_super_admins',
            new_callable=AsyncMock,
        ) as notify:
            # Must not re-raise.
            await DepartmentDeletionHandler.on_deleted(
                dept_id=7, deletion_source='manual',
            )
        notify.assert_awaited_once()


# =========================================================================
# _list_global_super_admin_ids — FGA query path (code-review LOW #3)
# =========================================================================

@pytest.mark.asyncio
class TestListGlobalSuperAdminIds:

    async def test_fga_returns_user_ids_parsed_from_tuples(self):
        """Happy path: FGA returns ['user:1', 'user:42'] → [1, 42]."""
        from bisheng.tenant.domain.services.department_deletion_handler import (
            _list_global_super_admin_ids,
        )
        fake_fga = MagicMock()
        fake_fga.list_users = AsyncMock(return_value=['user:1', 'user:42'])
        with patch(
            'bisheng.core.openfga.manager.aget_fga_client',
            new_callable=AsyncMock, return_value=fake_fga,
        ):
            result = await _list_global_super_admin_ids()
        assert sorted(result) == [1, 42]
        fake_fga.list_users.assert_awaited_once_with(
            object='system:global', relation='super_admin', user_type='user',
        )

    async def test_fga_unavailable_falls_back_to_empty(self):
        """FGA client=None → returns [] without raising."""
        from bisheng.tenant.domain.services.department_deletion_handler import (
            _list_global_super_admin_ids,
        )
        with patch(
            'bisheng.core.openfga.manager.aget_fga_client',
            new_callable=AsyncMock, return_value=None,
        ):
            result = await _list_global_super_admin_ids()
        assert result == []

    async def test_fga_exception_falls_back_to_empty(self):
        """FGA connection failure is caught — caller sees [] (not propagate)."""
        from bisheng.tenant.domain.services.department_deletion_handler import (
            _list_global_super_admin_ids,
        )
        with patch(
            'bisheng.core.openfga.manager.aget_fga_client',
            new_callable=AsyncMock, side_effect=ConnectionError('fga down'),
        ):
            result = await _list_global_super_admin_ids()
        assert result == []

    async def test_malformed_tuples_without_colon_are_skipped(self):
        """Defensive: malformed tuples like 'invalid' skip silently."""
        from bisheng.tenant.domain.services.department_deletion_handler import (
            _list_global_super_admin_ids,
        )
        fake_fga = MagicMock()
        fake_fga.list_users = AsyncMock(
            return_value=['user:5', 'invalid', 'user:7'],
        )
        with patch(
            'bisheng.core.openfga.manager.aget_fga_client',
            new_callable=AsyncMock, return_value=fake_fga,
        ):
            result = await _list_global_super_admin_ids()
        assert sorted(result) == [5, 7]

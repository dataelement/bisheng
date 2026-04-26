"""Status-machine guard: ``archived`` is terminal.

After ``unmount_child`` archives a Child Tenant, the dept's mount flag is
already cleared and resources have been migrated back to Root. Resuming
the row to ``active`` (or even ``disabled``) leaves a tenant with no
mount point — the orphans we explicitly fixed in F030. The status update
service must reject any transition out of ``archived`` and the frontend
hides the enable/disable toggle on archived rows.

These tests pin the service-side guard so the frontend can rely on it.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mirror the stub trick from test_tenant_disable_jwt_revoke.py so the lazy
# import of ``UserService`` inside ``_revoke_active_jwts_for_tenant`` does
# not pull ``minio`` into the test venv.
_USER_SERVICE_MODULE = 'bisheng.user.domain.services.user'
if _USER_SERVICE_MODULE not in sys.modules:
    _stub = MagicMock()
    _stub.UserService = MagicMock()
    _stub.UserService.ainvalidate_jwt_after_account_disabled = AsyncMock()
    sys.modules[_USER_SERVICE_MODULE] = _stub


def _mock_tenant(tenant_id: int, status: str):
    return type('T', (), {
        'id': tenant_id,
        'tenant_code': f'child{tenant_id}',
        'tenant_name': f'Child {tenant_id}',
        'status': status,
        'logo': None,
        'root_dept_id': None,
        'contact_name': None,
        'contact_phone': None,
        'contact_email': None,
        'quota_config': None,
        'create_time': None,
        'update_time': None,
        'model_dump': lambda self, include=None: {
            'id': tenant_id, 'status': status,
        },
    })()


@pytest.fixture()
def fake_super_admin():
    u = MagicMock()
    u.user_id = 99
    u.user_name = 'super'
    u.tenant_id = 1
    return u


@pytest.fixture()
def patched_status_flow():
    base = 'bisheng.tenant.domain.services.tenant_service'
    with patch(f'{base}.TenantDao.aget_by_id', new_callable=AsyncMock) as aget, \
         patch(f'{base}.TenantDao.aupdate_tenant', new_callable=AsyncMock) as aupd, \
         patch(f'{base}.UserTenantDao.aget_active_user_ids_by_tenant',
               new_callable=AsyncMock) as alist, \
         patch(f'{base}.AuditLogDao.ainsert_v2', new_callable=AsyncMock) as audit, \
         patch(f'{base}.get_redis_client', new_callable=AsyncMock) as redis_getter:
        redis_getter.return_value = AsyncMock()
        yield {
            'aget_by_id': aget,
            'aupdate_tenant': aupd,
            'list_active_users': alist,
            'audit_insert': audit,
        }


@pytest.mark.asyncio
class TestArchivedIsTerminal:

    async def test_archived_to_active_is_rejected(
        self, patched_status_flow, fake_super_admin,
    ):
        from bisheng.common.errcode.tenant_tree import TenantArchivedNotResumableError
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'archived')

        with pytest.raises(TenantArchivedNotResumableError):
            await TenantService.aupdate_tenant_status(
                tenant_id=5,
                data=TenantStatusUpdate(status='active'),
                login_user=fake_super_admin,
            )

        # Guard fires before the DB write — no UPDATE leaks through.
        patched_status_flow['aupdate_tenant'].assert_not_awaited()

    async def test_archived_to_disabled_is_rejected(
        self, patched_status_flow, fake_super_admin,
    ):
        from bisheng.common.errcode.tenant_tree import TenantArchivedNotResumableError
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'archived')

        with pytest.raises(TenantArchivedNotResumableError):
            await TenantService.aupdate_tenant_status(
                tenant_id=5,
                data=TenantStatusUpdate(status='disabled'),
                login_user=fake_super_admin,
            )

    async def test_archived_to_archived_is_idempotent(
        self, patched_status_flow, fake_super_admin,
    ):
        """Repeated archive call (e.g. retry on a flaky network) must not
        fire the guard — we only block transitions *out* of archived."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'archived')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'archived')

        # No exception expected.
        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='archived'),
            login_user=fake_super_admin,
        )
        patched_status_flow['aupdate_tenant'].assert_awaited_once()

    async def test_active_to_disabled_unchanged(
        self, patched_status_flow, fake_super_admin,
    ):
        """Sanity: the new guard must not regress the existing
        active → disabled path (covered separately in
        test_tenant_disable_jwt_revoke.py)."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'active')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'disabled')
        patched_status_flow['list_active_users'].return_value = []

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='disabled'),
            login_user=fake_super_admin,
        )
        patched_status_flow['aupdate_tenant'].assert_awaited_once()

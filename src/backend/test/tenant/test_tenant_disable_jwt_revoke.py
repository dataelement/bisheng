"""Tests for PRD §5.1.3 step 1: JWT revocation on Child Tenant disable.

Implementation lives in §11.9.11 of the tech design:
``TenantService.aupdate_tenant_status`` detects a non-disabled → disabled
transition and calls ``_revoke_active_jwts_for_tenant`` which:
  - bumps ``user.token_version`` for every active leaf user (via
    ``UserService.ainvalidate_jwt_after_account_disabled``)
  - writes one audit_log entry with action='tenant.disable'
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ``UserService.ainvalidate_jwt_after_account_disabled`` is lazy-imported
# inside ``TenantService._revoke_active_jwts_for_tenant``. The real module
# transitively imports ``minio`` which is not in the test venv, so we
# inject a stub module before the lazy import has a chance to resolve.
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
    """Patch every collaborator the service touches during status update.

    Yields a dict of mocks so each test can drive ``prior``/``updated``
    tenant rows and assert against ``invalidate_jwt`` / ``audit_log`` calls.
    """
    base = 'bisheng.tenant.domain.services.tenant_service'
    invalidate = AsyncMock()
    sys.modules[_USER_SERVICE_MODULE].UserService.\
        ainvalidate_jwt_after_account_disabled = invalidate
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
            'invalidate_jwt': invalidate,
        }


@pytest.mark.asyncio
class TestTenantDisableJwtRevocation:

    async def test_active_to_disabled_revokes_only_active_users(
        self, patched_status_flow, fake_super_admin,
    ):
        """TC1: prior=active, new=disabled → bump every active leaf user."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'active')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'disabled')
        # 3 active leaf users; historical (is_active=NULL) rows are excluded
        # by the DAO query, so the service only sees the 3 IDs.
        patched_status_flow['list_active_users'].return_value = [101, 102, 103]

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='disabled'),
            login_user=fake_super_admin,
        )

        invalidate = patched_status_flow['invalidate_jwt']
        assert invalidate.await_count == 3
        called_ids = sorted(call.args[0] for call in invalidate.await_args_list)
        assert called_ids == [101, 102, 103]

    async def test_disabled_to_disabled_is_idempotent(
        self, patched_status_flow, fake_super_admin,
    ):
        """TC2: prior already disabled → no JWT bump on repeat call."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'disabled')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'disabled')

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='disabled'),
            login_user=fake_super_admin,
        )

        patched_status_flow['list_active_users'].assert_not_awaited()
        patched_status_flow['invalidate_jwt'].assert_not_awaited()
        patched_status_flow['audit_insert'].assert_not_awaited()

    async def test_reenable_does_not_bump(
        self, patched_status_flow, fake_super_admin,
    ):
        """TC3: disabled → active should leave token_version untouched.

        Old JWTs are already invalid; users must re-login to get a fresh
        token. Bumping again would be a no-op for new tokens but creates
        unnecessary cache churn.
        """
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'disabled')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'active')

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='active'),
            login_user=fake_super_admin,
        )

        patched_status_flow['invalidate_jwt'].assert_not_awaited()
        patched_status_flow['audit_insert'].assert_not_awaited()

    async def test_disable_writes_audit_log_with_revoked_ids(
        self, patched_status_flow, fake_super_admin,
    ):
        """TC4: audit_log entry carries the exact list of revoked user_ids."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate
        from bisheng.tenant.domain.constants import TenantAuditAction

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'active')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'disabled')
        patched_status_flow['list_active_users'].return_value = [201, 202]

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='disabled'),
            login_user=fake_super_admin,
        )

        audit = patched_status_flow['audit_insert']
        audit.assert_awaited_once()
        kwargs = audit.await_args.kwargs
        assert kwargs['action'] == TenantAuditAction.DISABLE.value
        assert kwargs['tenant_id'] == 5
        assert kwargs['operator_id'] == 99
        assert kwargs['operator_tenant_id'] == 1  # ROOT_TENANT_ID
        assert kwargs['target_type'] == 'tenant'
        assert kwargs['target_id'] == '5'
        meta = kwargs['metadata']
        assert meta['revoked_user_ids'] == [201, 202]
        assert meta['revoked_count'] == 2
        assert meta['jwt_revoke'] is True

    async def test_individual_bump_failure_does_not_block_others(
        self, patched_status_flow, fake_super_admin,
    ):
        """A failing bump for one user must not stop the rest or the audit log."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        patched_status_flow['aget_by_id'].return_value = _mock_tenant(5, 'active')
        patched_status_flow['aupdate_tenant'].return_value = _mock_tenant(5, 'disabled')
        patched_status_flow['list_active_users'].return_value = [301, 302, 303]

        # Second call raises; first and third should still be attempted.
        patched_status_flow['invalidate_jwt'].side_effect = [
            None, RuntimeError('redis down'), None,
        ]

        await TenantService.aupdate_tenant_status(
            tenant_id=5,
            data=TenantStatusUpdate(status='disabled'),
            login_user=fake_super_admin,
        )

        assert patched_status_flow['invalidate_jwt'].await_count == 3
        patched_status_flow['audit_insert'].assert_awaited_once()

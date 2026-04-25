"""Tests for F011 Root tenant protection (INV-T11, AC-11, AC-15).

Test-First: written BEFORE the TenantService guard swap. Expected to fail
with ``TenantNotFoundError`` until the Service is updated to raise
``TenantTreeRootProtectedError`` (code 22008).

Scope:
  - ``aupdate_tenant_status(tenant_id=1, ...)`` → raises 22008
  - ``adelete_tenant(tenant_id=1, ...)`` → raises 22008
  - ``aupdate_tenant_status`` on a non-root tenant still works
  - ``adelete_tenant`` on a non-root tenant still works
  - Root backend guard fires before DAO (no DB side-effects on the Root).
"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.tenant_tree import TenantTreeRootProtectedError


@pytest.fixture()
def fake_user():
    """Minimal login_user passed to TenantService methods."""
    from unittest.mock import MagicMock
    u = MagicMock()
    u.user_id = 99
    u.user_name = 'tester'
    u.tenant_id = 1
    return u


# =========================================================================
# aupdate_tenant_status Root protection
# =========================================================================

@pytest.mark.asyncio
class TestAupdateTenantStatusRootProtection:

    async def test_root_id_raises_22008(self, fake_user):
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        with pytest.raises(TenantTreeRootProtectedError) as exc_info:
            await TenantService.aupdate_tenant_status(
                tenant_id=1,
                data=TenantStatusUpdate(status='disabled'),
                login_user=fake_user,
            )
        assert exc_info.value.Code == 22008

    async def test_root_protection_does_not_touch_dao(self, fake_user):
        """Guard must fire before any DAO call on the Root."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        with patch(
            'bisheng.tenant.domain.services.tenant_service.TenantDao.aupdate_tenant',
            new_callable=AsyncMock,
        ) as dao_mock:
            with pytest.raises(TenantTreeRootProtectedError):
                await TenantService.aupdate_tenant_status(
                    tenant_id=1,
                    data=TenantStatusUpdate(status='archived'),
                    login_user=fake_user,
                )
            dao_mock.assert_not_called()

    async def test_child_tenant_status_update_passes_guard(self, fake_user):
        """Non-root id proceeds to DAO (other behaviours mocked)."""
        from bisheng.tenant.domain.services.tenant_service import TenantService
        from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate

        mock_tenant = type('T', (), {
            'id': 5, 'tenant_code': 'child', 'tenant_name': 'Child',
            'status': 'disabled', 'logo': None, 'root_dept_id': None,
            'contact_name': None, 'contact_phone': None, 'contact_email': None,
            'quota_config': None, 'create_time': None, 'update_time': None,
            'model_dump': lambda self, include=None: {'id': 5, 'status': 'disabled'},
        })()

        with patch(
            'bisheng.tenant.domain.services.tenant_service.TenantDao.aget_by_id',
            new_callable=AsyncMock, return_value=mock_tenant,
        ), patch(
            'bisheng.tenant.domain.services.tenant_service.TenantDao.aupdate_tenant',
            new_callable=AsyncMock, return_value=mock_tenant,
        ), patch(
            'bisheng.tenant.domain.services.tenant_service.get_redis_client',
            new_callable=AsyncMock,
        ) as redis_getter:
            redis_mock = AsyncMock()
            redis_getter.return_value = redis_mock
            result = await TenantService.aupdate_tenant_status(
                tenant_id=5,
                data=TenantStatusUpdate(status='disabled'),
                login_user=fake_user,
            )
        # Prior status was already 'disabled' (mock returned the same row),
        # so no JWT revocation should fire — this test stays focused on the
        # root-protection guard, not the §11.9.11 revocation pathway.
        assert result['status'] == 'disabled'


# =========================================================================
# adelete_tenant Root protection
# =========================================================================

@pytest.mark.asyncio
class TestAdeleteTenantRootProtection:

    async def test_root_id_raises_22008(self, fake_user):
        from bisheng.tenant.domain.services.tenant_service import TenantService

        with pytest.raises(TenantTreeRootProtectedError):
            await TenantService.adelete_tenant(tenant_id=1, login_user=fake_user)

    async def test_root_protection_does_not_call_dao(self, fake_user):
        from bisheng.tenant.domain.services.tenant_service import TenantService

        with patch(
            'bisheng.tenant.domain.services.tenant_service.TenantDao.adelete_tenant',
            new_callable=AsyncMock,
        ) as dao_mock, patch(
            'bisheng.tenant.domain.services.tenant_service.TenantDao.acount_tenant_users',
            new_callable=AsyncMock, return_value=0,
        ):
            with pytest.raises(TenantTreeRootProtectedError):
                await TenantService.adelete_tenant(
                    tenant_id=1, login_user=fake_user,
                )
            dao_mock.assert_not_called()


# =========================================================================
# Error code payload / message contract
# =========================================================================

class TestTenantTreeRootProtectedErrorShape:

    def test_code_is_22008(self):
        assert TenantTreeRootProtectedError.Code == 22008

    def test_message_mentions_protection(self):
        msg = TenantTreeRootProtectedError.Msg.lower()
        assert 'root' in msg and 'protect' in msg

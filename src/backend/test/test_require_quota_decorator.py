"""Unit tests for require_quota decorator — sync/async compatibility + enforcement.

Tests:
  - Async endpoint: decorator calls check_quota, raises on exceeded
  - Sync endpoint: decorator wraps correctly without 'await sync_fn' error
  - No login_user kwarg: decorator skips check, calls original function
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_login_user():
    user = MagicMock()
    user.user_id = 10
    user.tenant_id = 1
    user.is_admin.return_value = False
    return user


class TestRequireQuotaAsync:
    """Decorator applied to async endpoint functions."""

    @pytest.mark.asyncio
    async def test_calls_check_quota_before_endpoint(self, mock_login_user):
        """Decorator calls QuotaService.check_quota before the wrapped function."""
        from bisheng.role.domain.services.quota_service import require_quota, QuotaResourceType

        call_order = []

        @require_quota(QuotaResourceType.WORKFLOW)
        async def create_workflow(*, login_user=None):
            call_order.append('endpoint')
            return {'id': 1}

        with patch(
            'bisheng.role.domain.services.quota_service.QuotaService.check_quota',
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.side_effect = lambda **kw: call_order.append('check_quota')
            result = await create_workflow(login_user=mock_login_user)

        assert call_order == ['check_quota', 'endpoint']
        assert result == {'id': 1}
        mock_check.assert_called_once_with(
            user_id=10,
            resource_type='workflow',
            tenant_id=1,
            login_user=mock_login_user,
        )

    @pytest.mark.asyncio
    async def test_raises_when_quota_exceeded(self, mock_login_user):
        """Decorator propagates TenantQuotaExceededError from check_quota (F016 T04)."""
        from bisheng.role.domain.services.quota_service import require_quota, QuotaResourceType
        from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError

        endpoint_called = False

        @require_quota(QuotaResourceType.KNOWLEDGE_SPACE)
        async def create_space(*, login_user=None):
            nonlocal endpoint_called
            endpoint_called = True

        with patch(
            'bisheng.role.domain.services.quota_service.QuotaService.check_quota',
            new_callable=AsyncMock,
            side_effect=TenantQuotaExceededError(),
        ):
            with pytest.raises(TenantQuotaExceededError):
                await create_space(login_user=mock_login_user)

        assert not endpoint_called

    @pytest.mark.asyncio
    async def test_skips_check_when_no_login_user(self):
        """Decorator skips quota check if login_user is not in kwargs."""
        from bisheng.role.domain.services.quota_service import require_quota, QuotaResourceType

        @require_quota(QuotaResourceType.TOOL)
        async def internal_create():
            return 'ok'

        with patch(
            'bisheng.role.domain.services.quota_service.QuotaService.check_quota',
            new_callable=AsyncMock,
        ) as mock_check:
            result = await internal_create()

        assert result == 'ok'
        mock_check.assert_not_called()


class TestRequireQuotaSync:
    """Decorator applied to sync (non-async) endpoint functions."""

    @pytest.mark.asyncio
    async def test_sync_function_works(self, mock_login_user):
        """Decorator wraps sync functions without 'await non-coroutine' error."""
        from bisheng.role.domain.services.quota_service import require_quota, QuotaResourceType

        @require_quota(QuotaResourceType.WORKFLOW)
        def create_flow_sync(*, login_user=None):
            return {'id': 42}

        with patch(
            'bisheng.role.domain.services.quota_service.QuotaService.check_quota',
            new_callable=AsyncMock,
        ) as mock_check:
            result = await create_flow_sync(login_user=mock_login_user)

        assert result == {'id': 42}
        mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_function_raises_on_exceeded(self, mock_login_user):
        """Sync function also gets blocked by TenantQuotaExceededError (F016 T04)."""
        from bisheng.role.domain.services.quota_service import require_quota, QuotaResourceType
        from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError

        @require_quota(QuotaResourceType.CHANNEL)
        def create_channel_sync(*, login_user=None):
            return 'should not reach'

        with patch(
            'bisheng.role.domain.services.quota_service.QuotaService.check_quota',
            new_callable=AsyncMock,
            side_effect=TenantQuotaExceededError(),
        ):
            with pytest.raises(TenantQuotaExceededError):
                await create_channel_sync(login_user=mock_login_user)

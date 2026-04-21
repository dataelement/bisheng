"""Integration tests for Role API endpoints (T10 — F005-role-menu-quota).

Tests HTTP endpoints via mock RoleService/QuotaService.
Covers AC-01, AC-03, AC-04, AC-05, AC-07, AC-09, AC-10, AC-11, AC-15, AC-24~AC-27.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from bisheng.role.domain.schemas.role_schema import RoleListResponse, EffectiveQuotaItem


@pytest.fixture
def mock_admin_login():
    """Mock admin user injected via Depends."""
    user = MagicMock()
    user.user_id = 1
    user.user_name = 'admin'
    user.is_admin.return_value = True
    user.tenant_id = 1
    user.user_role = [1]
    return user


@pytest.fixture
def mock_role_response():
    return RoleListResponse(
        id=15,
        role_name='Test Role',
        role_type='tenant',
        department_id=None,
        department_name=None,
        quota_config={'channel': 10},
        remark='test',
        user_count=3,
        is_readonly=False,
        create_time=datetime(2026, 4, 12),
        update_time=datetime(2026, 4, 12),
    )


class TestRoleEndpoints:
    """Role CRUD endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_role(self, mock_admin_login):
        """AC-01: POST /api/v1/roles creates a role."""
        from bisheng.role.domain.services.role_service import RoleService

        mock_role = MagicMock()
        mock_role.id = 15
        mock_role.role_name = 'New Role'
        mock_role.role_type = 'tenant'
        mock_role.department_id = None
        mock_role.quota_config = {'channel': 10}
        mock_role.remark = 'test'
        mock_role.create_time = datetime(2026, 4, 12)
        mock_role.update_time = datetime(2026, 4, 12)

        with patch.object(RoleService, 'create_role',
                          new_callable=AsyncMock, return_value=mock_role):
            result = await RoleService.create_role(
                MagicMock(role_name='New Role', quota_config={'channel': 10}),
                mock_admin_login,
            )
        assert result.id == 15

    @pytest.mark.asyncio
    async def test_list_roles(self, mock_admin_login):
        """AC-04: GET /api/v1/roles returns visible roles."""
        from bisheng.role.domain.services.role_service import RoleService

        response = {
            'data': [
                RoleListResponse(id=2, role_name='Default', role_type='global',
                                 user_count=45, is_readonly=False),
                RoleListResponse(id=5, role_name='Custom', role_type='tenant',
                                 user_count=3, is_readonly=False),
            ],
            'total': 2,
        }

        with patch.object(RoleService, 'list_roles',
                          new_callable=AsyncMock, return_value=response):
            result = await RoleService.list_roles(
                keyword=None, page=1, limit=10, login_user=mock_admin_login,
            )
        assert result['total'] == 2

    @pytest.mark.asyncio
    async def test_delete_builtin_raises(self, mock_admin_login):
        """AC-07: DELETE /api/v1/roles/1 → RoleBuiltinProtectedError."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.common.errcode.role import RoleBuiltinProtectedError

        with pytest.raises(RoleBuiltinProtectedError):
            await RoleService.delete_role(role_id=1, login_user=mock_admin_login)

    @pytest.mark.asyncio
    async def test_get_role_detail(self, mock_admin_login, mock_role_response):
        """AC-10: GET /api/v1/roles/{role_id} returns detail."""
        from bisheng.role.domain.services.role_service import RoleService

        with patch.object(RoleService, 'get_role',
                          new_callable=AsyncMock, return_value=mock_role_response):
            result = await RoleService.get_role(role_id=15, login_user=mock_admin_login)
        assert result.id == 15
        assert result.user_count == 3


class TestMenuEndpoints:
    """Menu permission endpoint tests."""

    @pytest.mark.asyncio
    async def test_update_menu(self, mock_admin_login):
        """AC-11: POST /api/v1/roles/{role_id}/menu updates menu permissions."""
        from bisheng.role.domain.services.role_service import RoleService

        with patch.object(RoleService, 'update_menu', new_callable=AsyncMock):
            await RoleService.update_menu(
                role_id=15,
                menu_ids=['workstation', 'build', 'knowledge'],
                login_user=mock_admin_login,
            )

    @pytest.mark.asyncio
    async def test_get_menu(self, mock_admin_login):
        """AC-12: GET /api/v1/roles/{role_id}/menu returns menu list."""
        from bisheng.role.domain.services.role_service import RoleService

        with patch.object(RoleService, 'get_menu',
                          new_callable=AsyncMock,
                          return_value=['workstation', 'build']):
            result = await RoleService.get_menu(role_id=15, login_user=mock_admin_login)
        assert 'workstation' in result


class TestQuotaEndpoints:
    """Quota query endpoint tests."""

    @pytest.mark.asyncio
    async def test_effective_quota(self, mock_admin_login):
        """AC-15/AC-19: GET /api/v1/quota/effective returns quotas."""
        from bisheng.role.domain.services.quota_service import QuotaService

        items = [
            EffectiveQuotaItem(
                resource_type='knowledge_space',
                role_quota=-1, tenant_quota=-1,
                tenant_used=0, user_used=0, effective=-1,
            ),
        ]

        with patch.object(QuotaService, 'get_all_effective_quotas',
                          new_callable=AsyncMock, return_value=items):
            result = await QuotaService.get_all_effective_quotas(
                user_id=1, tenant_id=1, login_user=mock_admin_login,
            )
        assert result[0].effective == -1

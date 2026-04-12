"""Unit tests for RoleService (T08 — F005-role-menu-quota).

Covers AC-01~AC-12: role CRUD, scope filtering, builtin protection,
menu permissions, permission checks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_admin_user():
    user = MagicMock()
    user.user_id = 1
    user.is_admin.return_value = True
    user.tenant_id = 1
    return user


@pytest.fixture
def mock_tenant_admin():
    """Non-system-admin but tenant admin."""
    user = MagicMock()
    user.user_id = 5
    user.is_admin.return_value = False
    user.tenant_id = 1
    return user


@pytest.fixture
def mock_normal_user():
    user = MagicMock()
    user.user_id = 10
    user.is_admin.return_value = False
    user.tenant_id = 1
    return user


def _make_role(role_id, role_name='Test Role', role_type='tenant',
               department_id=None, quota_config=None, tenant_id=1):
    role = MagicMock()
    role.id = role_id
    role.role_name = role_name
    role.role_type = role_type
    role.department_id = department_id
    role.quota_config = quota_config
    role.tenant_id = tenant_id
    role.remark = None
    role.create_time = None
    role.update_time = None
    return role


class TestCreateRole:
    """AC-01, AC-02, AC-09, AC-10b, AC-10c."""

    @pytest.mark.asyncio
    async def test_tenant_admin_creates_tenant_role(self, mock_tenant_admin):
        """AC-01: Tenant admin creates role → role_type='tenant'."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest

        req = RoleCreateRequest(role_name='Test Role', quota_config={'channel': 10})

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            created_role = _make_role(15, 'Test Role')
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_tenant_admin)

        assert result.id == 15

    @pytest.mark.asyncio
    async def test_admin_creates_global_role(self, mock_admin_user):
        """AC-02: System admin creates global role → role_type='global'."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest

        req = RoleCreateRequest(role_name='Global Template')

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            created_role = _make_role(16, 'Global Template', role_type='global')
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_admin_user)

        assert result.role_type == 'global'

    @pytest.mark.asyncio
    async def test_duplicate_name_raises(self, mock_tenant_admin):
        """AC-09: Duplicate role_name in same scope → 24002."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.common.errcode.role import RoleNameDuplicateError

        req = RoleCreateRequest(role_name='Existing Role')

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            mock_dao.aget_role_by_name = AsyncMock(return_value=_make_role(3, 'Existing Role'))
            mock_qs.validate_quota_config = MagicMock()

            with pytest.raises(RoleNameDuplicateError):
                await RoleService.create_role(req, mock_tenant_admin)

    @pytest.mark.asyncio
    async def test_invalid_quota_config_raises(self, mock_tenant_admin):
        """AC-10c: Invalid quota_config values → 24005."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.common.errcode.role import QuotaConfigInvalidError

        req = RoleCreateRequest(role_name='Bad Quota', quota_config={'channel': -5})

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock):
            with pytest.raises(QuotaConfigInvalidError):
                await RoleService.create_role(req, mock_tenant_admin)

    @pytest.mark.asyncio
    async def test_normal_user_denied(self, mock_normal_user):
        """AC-10b: Regular user calling role mgmt API → 24003."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.common.errcode.role import RolePermissionDeniedError

        req = RoleCreateRequest(role_name='Nope')

        with pytest.raises(RolePermissionDeniedError):
            await RoleService.create_role(req, mock_normal_user)


class TestListRoles:
    """AC-03, AC-04, AC-04b."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_except_adminrole(self, mock_admin_user):
        """AC-04: System admin sees all roles except AdminRole(id=1)."""
        from bisheng.role.domain.services.role_service import RoleService

        roles = [_make_role(2, 'Default'), _make_role(5, 'Custom')]

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao:
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={2: 45, 5: 3})

            result = await RoleService.list_roles(
                keyword=None, page=1, limit=10,
                login_user=mock_admin_user,
            )

        assert result['total'] == 2
        # Admin can edit all
        for item in result['data']:
            assert item.is_readonly is False

    @pytest.mark.asyncio
    async def test_tenant_admin_sees_global_readonly(self, mock_tenant_admin):
        """AC-03: Tenant admin sees global roles as readonly."""
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(2, 'Default', role_type='global'),
            _make_role(5, 'Custom', role_type='tenant'),
        ]

        with patch.object(RoleService, '_check_list_permission', new_callable=AsyncMock,
                          return_value='tenant_admin'), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao:
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={2: 45, 5: 3})

            result = await RoleService.list_roles(
                keyword=None, page=1, limit=10,
                login_user=mock_tenant_admin,
            )

        global_items = [i for i in result['data'] if i.role_type == 'global']
        tenant_items = [i for i in result['data'] if i.role_type == 'tenant']
        assert all(i.is_readonly for i in global_items)
        assert all(not i.is_readonly for i in tenant_items)


class TestDeleteRole:
    """AC-07, AC-08."""

    @pytest.mark.asyncio
    async def test_delete_builtin_role_raises(self, mock_admin_user):
        """AC-07: Deleting AdminRole or DefaultRole → 24004."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.common.errcode.role import RoleBuiltinProtectedError

        with pytest.raises(RoleBuiltinProtectedError):
            await RoleService.delete_role(role_id=1, login_user=mock_admin_user)

    @pytest.mark.asyncio
    async def test_delete_builtin_default_role_raises(self, mock_admin_user):
        """AC-07: DefaultRole(id=2) also protected."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.common.errcode.role import RoleBuiltinProtectedError

        with pytest.raises(RoleBuiltinProtectedError):
            await RoleService.delete_role(role_id=2, login_user=mock_admin_user)

    @pytest.mark.asyncio
    async def test_delete_role_cascades(self, mock_admin_user):
        """AC-08: Delete role cascades UserRole + RoleAccess."""
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, 'Deletable')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao:
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.adelete_role = AsyncMock()

            await RoleService.delete_role(role_id=15, login_user=mock_admin_user)

        mock_dao.adelete_role.assert_called_once_with(15)


class TestUpdateRole:
    """AC-05, AC-06."""

    @pytest.mark.asyncio
    async def test_update_role_succeeds(self, mock_admin_user):
        """AC-05: Update role_name/quota_config/remark."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest

        role = _make_role(15, 'Old Name', role_type='tenant')
        req = RoleUpdateRequest(role_name='New Name')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.update_role = AsyncMock(return_value=role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.update_role(
                role_id=15, req=req, login_user=mock_admin_user,
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_tenant_admin_cannot_update_global(self, mock_tenant_admin):
        """AC-06: Tenant admin updating global role → 24003."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.common.errcode.role import RolePermissionDeniedError

        role = _make_role(2, 'Default', role_type='global')
        req = RoleUpdateRequest(remark='hacked')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao:
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=2, req=req, login_user=mock_tenant_admin,
                )


class TestMenuPermissions:
    """AC-11, AC-12."""

    @pytest.mark.asyncio
    async def test_update_menu(self, mock_admin_user):
        """AC-11: Update role menu permissions."""
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, 'Test', role_type='tenant')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.role_service.RoleAccessDao') as mock_ra_dao:
            mock_role_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_ra_dao.update_role_access_all = AsyncMock()

            await RoleService.update_menu(
                role_id=15,
                menu_ids=['workstation', 'build', 'knowledge'],
                login_user=mock_admin_user,
            )

        mock_ra_dao.update_role_access_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_menu(self, mock_admin_user):
        """AC-12: Get role menu permissions."""
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, 'Test', role_type='tenant')
        menu_records = [MagicMock(third_id='workstation'), MagicMock(third_id='build')]

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.role_service.RoleAccessDao') as mock_ra_dao:
            mock_role_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_ra_dao.aget_role_access = AsyncMock(return_value=menu_records)

            result = await RoleService.get_menu(role_id=15, login_user=mock_admin_user)

        assert result == ['workstation', 'build']

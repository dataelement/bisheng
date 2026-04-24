"""Unit tests for RoleService (T08 — F005-role-menu-quota).

Covers AC-01~AC-12: role CRUD, scope filtering, builtin protection,
menu permissions, permission checks.
"""

import pytest
from contextlib import asynccontextmanager
from pathlib import Path
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


@pytest.fixture
def mock_dept_admin():
    user = MagicMock()
    user.user_id = 8
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
             patch('bisheng.role.domain.services.role_service.Role') as mock_role_cls, \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            created_role = MagicMock()
            created_role.id = 15
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_tenant_admin)

        assert result.id == 15
        mock_role_cls.assert_called_once_with(
            role_name='Test Role',
            role_type='tenant',
            department_id=None,
            quota_config={'channel': 10},
            remark=None,
            create_user=mock_tenant_admin.user_id,
        )

    @pytest.mark.asyncio
    async def test_admin_creates_global_role(self, mock_admin_user):
        """AC-02: System admin creates global role → role_type='global'."""
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest

        req = RoleCreateRequest(role_name='Global Template')

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.Role') as mock_role_cls, \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            created_role = MagicMock()
            created_role.id = 16
            created_role.role_type = 'global'
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_admin_user)

        assert result.role_type == 'global'
        mock_role_cls.assert_called_once_with(
            role_name='Global Template',
            role_type='global',
            department_id=None,
            quota_config=None,
            remark=None,
            create_user=mock_admin_user.user_id,
        )

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
    async def test_same_name_allowed_in_different_departments(self, mock_tenant_admin):
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest

        req = RoleCreateRequest(role_name='Existing Role', department_id=10)

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_validate_department', new_callable=AsyncMock), \
             patch.object(RoleService, '_ensure_create_scope', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.Role') as mock_role_cls, \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs:
            created_role = MagicMock()
            created_role.id = 18
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_tenant_admin)

        assert result.id == 18
        mock_dao.aget_role_by_name.assert_awaited_once_with(
            tenant_id=mock_tenant_admin.tenant_id,
            role_type='tenant',
            role_name='Existing Role',
            department_id=10,
        )

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

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_create_unscoped_role(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name='Dept Wide')

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='dept_admin'), \
             patch.object(RoleService, '_get_dept_subtree_ids', new_callable=AsyncMock,
                          return_value=[5, 6]):
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            with pytest.raises(RolePermissionDeniedError):
                await RoleService.create_role(req, mock_dept_admin)

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_create_role_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name='Out of Scope', department_id=99)

        with patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs, \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='dept_admin'), \
             patch.object(RoleService, '_get_dept_subtree_ids', new_callable=AsyncMock,
                          return_value=[5, 6]), \
             patch.object(RoleService, '_validate_department', new_callable=AsyncMock):
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_qs.validate_quota_config = MagicMock()

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.create_role(req, mock_dept_admin)


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

        with patch(
            'bisheng.database.models.department.DepartmentDao.aget_user_admin_departments',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={5: mock_tenant_admin.user_id}), \
             patch.object(RoleService, '_get_creator_names', new_callable=AsyncMock,
                          return_value={5: 'tenant-admin'}):
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

    @pytest.mark.asyncio
    async def test_tenant_admin_sees_missing_creator_role_as_readonly(self, mock_tenant_admin):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [_make_role(5, 'Custom', role_type='tenant')]

        with patch(
            'bisheng.database.models.department.DepartmentDao.aget_user_admin_departments',
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            'bisheng.permission.domain.services.permission_service.PermissionService.check',
            new_callable=AsyncMock,
            return_value=True,
        ), patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={}), \
             patch.object(RoleService, '_get_creator_names', new_callable=AsyncMock,
                          return_value={}):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=1)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={5: 3})

            result = await RoleService.list_roles(
                keyword=None, page=1, limit=10,
                login_user=mock_tenant_admin,
            )

        assert result['data'][0].is_readonly is True

    @pytest.mark.asyncio
    async def test_dept_admin_sees_global_scope_role_but_only_creator_can_edit(self, mock_dept_admin):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(5, 'Tenant Global Scope', role_type='tenant', department_id=None),
            _make_role(6, 'Scoped Tenant Role', role_type='tenant', department_id=8),
        ]

        admin_dept = MagicMock()
        admin_dept.id = 8
        admin_dept.path = '/8'

        with patch(
            'bisheng.database.models.department.DepartmentDao.aget_user_admin_departments',
            new_callable=AsyncMock,
            return_value=[admin_dept],
        ), patch(
            'bisheng.database.models.department.DepartmentDao.aget_subtree_ids',
            new_callable=AsyncMock,
            return_value=[8, 9],
        ), patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_get_department_names', new_callable=AsyncMock, return_value={}), \
             patch.object(RoleService, '_department_scope_paths_for_roles', new_callable=AsyncMock, return_value={}), \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={5: 99, 6: mock_dept_admin.user_id}), \
             patch.object(RoleService, '_get_creator_names', new_callable=AsyncMock,
                          return_value={5: 'other', 6: 'dept-admin'}):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={5: 1, 6: 2})

            result = await RoleService.list_roles(
                keyword=None, page=1, limit=10,
                login_user=mock_dept_admin,
            )

        readonly = {item.id: item.is_readonly for item in result['data']}
        assert readonly[5] is True
        assert readonly[6] is False


class TestRoleDaoVisibility:
    def test_dept_admin_query_includes_unscoped_tenant_roles(self):
        source = (
            Path(__file__).resolve().parents[1]
            / 'bisheng'
            / 'database'
            / 'models'
            / 'role.py'
        ).read_text(encoding='utf-8')

        assert "Role.department_id.is_(None)" in source
        assert "Role.department_id.in_(department_ids)" in source


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

    @pytest.mark.asyncio
    async def test_delete_role_requires_creator(self, mock_tenant_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, 'Owned By Another User')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='tenant_admin'), \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={15: 999}):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.delete_role(role_id=15, login_user=mock_tenant_admin)


class TestCreatorResolution:
    @pytest.mark.asyncio
    async def test_get_role_creator_ids_merges_audit_log_fallback(self):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [_make_role(15), _make_role(16)]

        with patch.object(RoleService, '_get_direct_role_creator_ids', new_callable=AsyncMock,
                          return_value={15: 5}), \
             patch.object(RoleService, '_get_audit_log_role_creator_ids', new_callable=AsyncMock,
                          return_value={16: 7}):
            result = await RoleService._get_role_creator_ids(roles)

        assert result == {15: 5, 16: 7}


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
    async def test_update_role_checks_duplicate_name_in_target_department_scope(self, mock_admin_user):
        from bisheng.role.domain.services.role_service import RoleService
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest

        role = _make_role(15, 'Old Name', role_type='tenant', department_id=5)
        req = RoleUpdateRequest(role_name='New Name', department_id=8)

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch('bisheng.role.domain.services.role_service.QuotaService') as mock_qs, \
             patch.object(RoleService, '_validate_department', new_callable=AsyncMock):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.update_role = AsyncMock(return_value=role)
            mock_qs.validate_quota_config = MagicMock()

            await RoleService.update_role(
                role_id=15, req=req, login_user=mock_admin_user,
            )

        mock_dao.aget_role_by_name.assert_awaited_once_with(
            tenant_id=mock_admin_user.tenant_id,
            role_type='tenant',
            role_name='New Name',
            department_id=8,
        )

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

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_update_role_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(18, 'Tenant Role', role_type='tenant', department_id=99)
        req = RoleUpdateRequest(remark='nope')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='dept_admin'), \
             patch.object(RoleService, '_get_dept_subtree_ids', new_callable=AsyncMock,
                          return_value=[5, 6]):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=18, req=req, login_user=mock_dept_admin,
                )

    @pytest.mark.asyncio
    async def test_update_role_requires_creator(self, mock_tenant_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(16, 'Editable?', role_type='tenant')
        req = RoleUpdateRequest(remark='attempt')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='tenant_admin'), \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={16: 998}):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=16, req=req, login_user=mock_tenant_admin,
                )

    @pytest.mark.asyncio
    async def test_update_role_missing_creator_defaults_to_readonly(self, mock_tenant_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(17, 'Legacy Role', role_type='tenant')
        req = RoleUpdateRequest(remark='attempt')

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='tenant_admin'), \
             patch.object(RoleService, '_get_role_creator_ids', new_callable=AsyncMock,
                          return_value={}):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=17, req=req, login_user=mock_tenant_admin,
                )


class TestMenuPermissions:
    """AC-11, AC-12."""

    @pytest.mark.asyncio
    async def test_update_menu(self, mock_admin_user):
        """AC-11: Update role menu permissions."""
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, 'Test', role_type='tenant')
        session = MagicMock()
        exec_result = MagicMock()
        exec_result.first.return_value = role
        session.exec = AsyncMock(return_value=exec_result)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield session

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_role_dao, \
             patch('bisheng.role.domain.services.role_service.select') as mock_select, \
             patch('bisheng.role.domain.services.role_service.get_async_db_session', fake_session), \
             patch.object(RoleService, '_replace_menu_access_in_session', new_callable=AsyncMock) as mock_replace:
            mock_role_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_select.return_value.where.return_value = MagicMock()

            await RoleService.update_menu(
                role_id=15,
                menu_ids=['workstation', 'build', 'knowledge'],
                login_user=mock_admin_user,
            )

        mock_replace.assert_called_once()
        assert role.update_time is not None
        session.add.assert_called_once_with(role)
        session.commit.assert_awaited_once()

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

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_update_menu_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(22, 'Tenant Role', role_type='tenant', department_id=99)

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_role_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_get_permission_level', new_callable=AsyncMock,
                          return_value='dept_admin'), \
             patch.object(RoleService, '_get_dept_subtree_ids', new_callable=AsyncMock,
                          return_value=[5, 6]):
            mock_role_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_menu(
                    role_id=22,
                    menu_ids=['workstation'],
                    login_user=mock_dept_admin,
                )

    @pytest.mark.asyncio
    async def test_update_role_with_menu_touches_update_time_on_menu_only_edit(self, mock_admin_user):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(25, 'Menu Only', role_type='tenant')
        req = RoleUpdateRequest(menu_ids=['workstation', 'knowledge'])
        session = MagicMock()
        exec_result = MagicMock()
        exec_result.first.return_value = role
        session.exec = AsyncMock(return_value=exec_result)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield session

        with patch('bisheng.role.domain.services.role_service.RoleDao') as mock_role_dao, \
             patch.object(RoleService, '_check_role_permission', new_callable=AsyncMock), \
             patch.object(RoleService, '_ensure_role_mutation_access', new_callable=AsyncMock), \
             patch('bisheng.role.domain.services.role_service.select') as mock_select, \
             patch('bisheng.role.domain.services.role_service.get_async_db_session', fake_session), \
             patch.object(RoleService, '_replace_menu_access_in_session', new_callable=AsyncMock) as mock_replace:
            mock_role_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_select.return_value.where.return_value = MagicMock()

            result = await RoleService.update_role_with_menu(
                role_id=25, req=req, login_user=mock_admin_user,
            )

        assert result is role
        assert role.update_time is not None
        session.add.assert_called_once_with(role)
        mock_replace.assert_called_once()
        session.commit.assert_awaited_once()

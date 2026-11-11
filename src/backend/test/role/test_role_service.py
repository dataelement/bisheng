"""Unit tests for RoleService (T08 — F005-role-menu-quota).

Covers AC-01~AC-12: role CRUD, scope filtering, builtin protection,
menu permissions, permission checks.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.role.domain.repositories.role_definition_repository import RoleDefinitionRepository


@pytest.fixture(autouse=True)
def definition_store(monkeypatch):
    """Service tests isolate persistence; real transactions are covered by F009 ORM tests."""

    async def create(role, menu_ids=None):
        return role

    async def update(role, changes, menu_ids=None, *, operator_id=None):
        for name, value in changes.items():
            setattr(role, name, value)
        return role

    store = MagicMock()
    store.create = AsyncMock(side_effect=create)
    store.update = AsyncMock(side_effect=update)
    store.delete = AsyncMock()
    store.menu = AsyncMock(return_value=[])
    for name in ("create", "update", "delete", "menu"):
        monkeypatch.setattr(RoleDefinitionRepository, name, getattr(store, name))
    return store


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


def _make_role(role_id, role_name="Test Role", role_type="tenant", department_id=None, quota_config=None, tenant_id=1):
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
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Test Role", quota_config={"channel": 10})

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
            created_role = MagicMock()
            created_role.id = 15
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_tenant_admin)

        assert result.id == 15
        mock_role_cls.assert_called_once_with(
            role_name="Test Role",
            role_type="tenant",
            department_id=None,
            quota_config={"channel": 10},
            remark=None,
            create_user=mock_tenant_admin.user_id,
            tenant_id=mock_tenant_admin.tenant_id,
        )

    @pytest.mark.asyncio
    async def test_admin_creates_global_role(self, mock_admin_user):
        """AC-02: System admin creates global role → role_type='global'."""
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Global Template")

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
            created_role = MagicMock()
            created_role.id = 16
            created_role.role_type = "global"
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.create_role(req, mock_admin_user)

        assert result.role_type == "global"
        mock_role_cls.assert_called_once_with(
            role_name="Global Template",
            role_type="global",
            department_id=None,
            quota_config=None,
            remark=None,
            create_user=mock_admin_user.user_id,
            tenant_id=mock_admin_user.tenant_id,
        )

    @pytest.mark.asyncio
    async def test_duplicate_name_raises(self, mock_tenant_admin):
        """AC-09: Duplicate role_name in same scope → 24002."""
        from bisheng.common.errcode.role import RoleNameDuplicateError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Existing Role")

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
            mock_dao.aget_role_by_name = AsyncMock(return_value=_make_role(3, "Existing Role"))
            mock_qs.validate_quota_config = MagicMock()

            with pytest.raises(RoleNameDuplicateError):
                await RoleService.create_role(req, mock_tenant_admin)

    @pytest.mark.asyncio
    async def test_same_name_allowed_in_different_departments(self, mock_tenant_admin):
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Existing Role", department_id=10)

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_validate_department", new_callable=AsyncMock),
            patch.object(RoleService, "_ensure_create_scope", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
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
            role_type="tenant",
            role_name="Existing Role",
            department_id=10,
        )

    @pytest.mark.asyncio
    async def test_invalid_quota_config_raises(self, mock_tenant_admin):
        """AC-10c: Invalid quota_config values → 24005."""
        from bisheng.common.errcode.role import QuotaConfigInvalidError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Bad Quota", quota_config={"channel": -5})

        with patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock):
            with pytest.raises(QuotaConfigInvalidError):
                await RoleService.create_role(req, mock_tenant_admin)

    @pytest.mark.asyncio
    async def test_normal_user_denied(self, mock_normal_user):
        """AC-10b: Regular user calling role mgmt API → 24003."""
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Nope")

        with pytest.raises(RolePermissionDeniedError):
            await RoleService.create_role(req, mock_normal_user)

    @pytest.mark.asyncio
    async def test_child_tenant_admin_role_carries_child_tenant_id(self):
        """Regression: child-tenant admin's role must persist with their tenant_id.

        Without explicitly passing ``tenant_id`` into the ``Role(...)`` constructor,
        the model default of 1 (Root) survived because the ``before_flush`` hook
        only auto-fills when the value is None/0 — so child-tenant admins created
        roles owned by Root and the tenant-scoped list query returned empty.
        """
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        child_admin = MagicMock()
        child_admin.user_id = 42
        child_admin.is_admin.return_value = False
        child_admin.tenant_id = 7

        req = RoleCreateRequest(role_name="Child Role")

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_ensure_create_scope", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
        ):
            created_role = MagicMock()
            created_role.id = 99
            created_role.tenant_id = 7
            mock_role_cls.return_value = created_role
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.ainsert_role = AsyncMock(return_value=created_role)

            await RoleService.create_role(req, child_admin)

        kwargs = mock_role_cls.call_args.kwargs
        assert kwargs["tenant_id"] == 7
        assert kwargs["role_type"] == "tenant"

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_create_unscoped_role(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Dept Wide")

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="dept_admin"),
            patch.object(RoleService, "_get_dept_subtree_ids", new_callable=AsyncMock, return_value=[5, 6]),
        ):
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            with pytest.raises(RolePermissionDeniedError):
                await RoleService.create_role(req, mock_dept_admin)

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_create_role_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
        from bisheng.role.domain.services.role_service import RoleService

        req = RoleCreateRequest(role_name="Out of Scope", department_id=99)

        with (
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="dept_admin"),
            patch.object(RoleService, "_get_dept_subtree_ids", new_callable=AsyncMock, return_value=[5, 6]),
            patch.object(RoleService, "_validate_department", new_callable=AsyncMock),
        ):
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

        roles = [_make_role(2, "Default"), _make_role(5, "Custom")]

        with patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao:
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={2: 45, 5: 3})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=10,
                login_user=mock_admin_user,
            )

        assert result["total"] == 2
        # Admin can edit all
        for item in result["data"]:
            assert item.is_readonly is False

    @pytest.mark.asyncio
    async def test_admin_can_edit_role_created_by_others(self, mock_admin_user):
        """System admin can edit roles even when the creator is someone else."""
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(5, "Custom Tenant", role_type="tenant", department_id=8),
            _make_role(6, "Global Other", role_type="global"),
        ]

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_get_department_names", new_callable=AsyncMock, return_value={}),
            patch.object(RoleService, "_department_scope_paths_for_roles", new_callable=AsyncMock, return_value={}),
            patch.object(RoleService, "_get_role_creator_ids", new_callable=AsyncMock, return_value={5: 99, 6: 42}),
            patch.object(
                RoleService,
                "_get_creator_names",
                new_callable=AsyncMock,
                return_value={5: "someone-else", 6: "another-user"},
            ),
        ):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={5: 1, 6: 2})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=10,
                login_user=mock_admin_user,
            )

        readonly = {item.id: item.is_readonly for item in result["data"]}
        assert readonly[5] is False
        assert readonly[6] is False

    @pytest.mark.asyncio
    async def test_tenant_admin_sees_global_readonly(self, mock_tenant_admin):
        """AC-03: Tenant admin sees global roles as readonly."""
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(2, "Default", role_type="global"),
            _make_role(5, "Custom", role_type="tenant"),
        ]

        with (
            patch(
                "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bisheng.permission.application.is_tenant_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(
                RoleService,
                "_get_role_creator_ids",
                new_callable=AsyncMock,
                return_value={5: mock_tenant_admin.user_id},
            ),
            patch.object(RoleService, "_get_creator_names", new_callable=AsyncMock, return_value={5: "tenant-admin"}),
        ):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={2: 45, 5: 3})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=10,
                login_user=mock_tenant_admin,
            )

        global_items = [i for i in result["data"] if i.role_type == "global"]
        tenant_items = [i for i in result["data"] if i.role_type == "tenant"]
        assert all(i.is_readonly for i in global_items)
        assert all(not i.is_readonly for i in tenant_items)

    @pytest.mark.asyncio
    async def test_tenant_admin_binding_catalog_includes_global_roles(self, mock_tenant_admin):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(2, "Default", role_type="global"),
            _make_role(5, "Custom", role_type="tenant"),
        ]

        with (
            patch(
                "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bisheng.permission.application.is_tenant_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(
                RoleService,
                "_get_role_creator_ids",
                new_callable=AsyncMock,
                return_value={5: mock_tenant_admin.user_id},
            ),
            patch.object(RoleService, "_get_creator_names", new_callable=AsyncMock, return_value={5: "tenant-admin"}),
        ):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={2: 45, 5: 3})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=0,
                login_user=mock_tenant_admin,
                include_global_for_binding=True,
            )

        assert result["total"] == 2
        mock_dao.aget_visible_roles.assert_awaited_once_with(
            tenant_id=mock_tenant_admin.tenant_id,
            keyword=None,
            page=1,
            limit=0,
            department_ids=None,
            tenant_custom_roles_only=False,
        )

    @pytest.mark.asyncio
    async def test_tenant_admin_can_edit_missing_creator_role(self, mock_tenant_admin):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [_make_role(5, "Custom", role_type="tenant")]

        with (
            patch(
                "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "bisheng.permission.application.is_tenant_admin",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_get_role_creator_ids", new_callable=AsyncMock, return_value={}),
            patch.object(RoleService, "_get_creator_names", new_callable=AsyncMock, return_value={}),
        ):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=1)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={5: 3})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=10,
                login_user=mock_tenant_admin,
            )

        assert result["data"][0].is_readonly is False

    @pytest.mark.asyncio
    async def test_dept_admin_sees_global_scope_role_but_only_creator_can_edit(self, mock_dept_admin):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [
            _make_role(5, "Tenant Global Scope", role_type="tenant", department_id=None),
            _make_role(6, "Scoped Tenant Role", role_type="tenant", department_id=8),
        ]

        admin_dept = MagicMock()
        admin_dept.id = 8
        admin_dept.path = "/8"

        with (
            patch(
                "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
                new_callable=AsyncMock,
                return_value=[admin_dept],
            ),
            patch(
                "bisheng.database.models.department.DepartmentDao.aget_subtree_ids",
                new_callable=AsyncMock,
                return_value=[8, 9],
            ),
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_get_department_names", new_callable=AsyncMock, return_value={}),
            patch.object(RoleService, "_department_scope_paths_for_roles", new_callable=AsyncMock, return_value={}),
            patch.object(
                RoleService,
                "_get_role_creator_ids",
                new_callable=AsyncMock,
                return_value={5: 99, 6: mock_dept_admin.user_id},
            ),
            patch.object(
                RoleService, "_get_creator_names", new_callable=AsyncMock, return_value={5: "other", 6: "dept-admin"}
            ),
        ):
            mock_dao.aget_visible_roles = AsyncMock(return_value=roles)
            mock_dao.acount_visible_roles = AsyncMock(return_value=2)
            mock_dao.aget_user_count_by_role_ids = AsyncMock(return_value={5: 1, 6: 2})

            result = await RoleService.list_roles(
                keyword=None,
                page=1,
                limit=10,
                login_user=mock_dept_admin,
            )

        readonly = {item.id: item.is_readonly for item in result["data"]}
        assert readonly[5] is True
        assert readonly[6] is False


class TestRoleDaoVisibility:
    def test_dept_admin_query_includes_unscoped_tenant_roles(self):
        source = (Path(__file__).resolve().parents[2] / "bisheng" / "database" / "models" / "role.py").read_text(
            encoding="utf-8"
        )

        assert "Role.department_id.is_(None)" in source
        assert "Role.department_id.in_(department_ids)" in source


class TestDeleteRole:
    """AC-07, AC-08."""

    @pytest.mark.asyncio
    async def test_delete_builtin_role_raises(self, mock_admin_user):
        """AC-07: Deleting AdminRole or DefaultRole → 24004."""
        from bisheng.common.errcode.role import RoleBuiltinProtectedError
        from bisheng.role.domain.services.role_service import RoleService

        with pytest.raises(RoleBuiltinProtectedError):
            await RoleService.delete_role(role_id=1, login_user=mock_admin_user)

    @pytest.mark.asyncio
    async def test_delete_builtin_default_role_raises(self, mock_admin_user):
        """AC-07: DefaultRole(id=2) also protected."""
        from bisheng.common.errcode.role import RoleBuiltinProtectedError
        from bisheng.role.domain.services.role_service import RoleService

        with pytest.raises(RoleBuiltinProtectedError):
            await RoleService.delete_role(role_id=2, login_user=mock_admin_user)

    @pytest.mark.asyncio
    async def test_delete_role_cascades(self, mock_admin_user):
        """AC-08: Delete role cascades UserRole + RoleAccess."""
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Deletable")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch(
                "bisheng.permission.domain.services.legacy_rbac_sync_service.LegacyRBACSyncService.sync_role_deleted",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.adelete_role = AsyncMock()

            await RoleService.delete_role(role_id=15, login_user=mock_admin_user)

        mock_sync.assert_awaited_once_with(15)
        RoleDefinitionRepository.delete.assert_awaited_once_with(role, operator_id=mock_admin_user.user_id)

    @pytest.mark.asyncio
    async def test_tenant_admin_can_delete_tenant_role_created_by_other_admin(self, mock_tenant_admin):
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Owned By Another User")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="tenant_admin"),
            patch.object(RoleService, "_get_role_creator_ids", new_callable=AsyncMock, return_value={15: 999}),
            patch(
                "bisheng.permission.domain.services.legacy_rbac_sync_service.LegacyRBACSyncService.sync_role_deleted",
                new_callable=AsyncMock,
            ) as mock_sync,
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.adelete_role = AsyncMock()

            await RoleService.delete_role(role_id=15, login_user=mock_tenant_admin)

        mock_sync.assert_awaited_once_with(15)
        RoleDefinitionRepository.delete.assert_awaited_once_with(role, operator_id=mock_tenant_admin.user_id)


class TestCreatorResolution:
    @pytest.mark.asyncio
    async def test_get_role_creator_ids_merges_audit_log_fallback(self):
        from bisheng.role.domain.services.role_service import RoleService

        roles = [_make_role(15), _make_role(16)]

        with (
            patch.object(RoleService, "_get_direct_role_creator_ids", new_callable=AsyncMock, return_value={15: 5}),
            patch.object(RoleService, "_get_audit_log_role_creator_ids", new_callable=AsyncMock, return_value={16: 7}),
        ):
            result = await RoleService._get_role_creator_ids(roles)

        assert result == {15: 5, 16: 7}

    @pytest.mark.asyncio
    async def test_get_creator_names_maps_system_admin_to_system_preset(self):
        from bisheng.role.domain.services.role_service import (
            SYSTEM_PRESET_CREATOR_NAME,
            RoleService,
        )

        admin_user = MagicMock()
        admin_user.user_id = 1
        admin_user.user_name = "admin"

        with (
            patch("bisheng.role.domain.services.role_service.UserDao") as mock_user_dao,
            patch.object(RoleService, "_get_system_admin_user_ids", new_callable=AsyncMock, return_value={1}),
        ):
            mock_user_dao.aget_user_by_ids = AsyncMock(return_value=[admin_user])

            result = await RoleService._get_creator_names({15: 1})

        assert result == {15: SYSTEM_PRESET_CREATOR_NAME}

    @pytest.mark.asyncio
    async def test_get_creator_names_keeps_regular_username(self):
        from bisheng.role.domain.services.role_service import RoleService

        normal_user = MagicMock()
        normal_user.user_id = 8
        normal_user.user_name = "alice"

        with (
            patch("bisheng.role.domain.services.role_service.UserDao") as mock_user_dao,
            patch.object(RoleService, "_get_system_admin_user_ids", new_callable=AsyncMock, return_value=set()),
        ):
            mock_user_dao.aget_user_by_ids = AsyncMock(return_value=[normal_user])

            result = await RoleService._get_creator_names({16: 8})

        assert result == {16: "alice"}


class TestUpdateRole:
    """AC-05, AC-06."""

    @pytest.mark.asyncio
    async def test_update_role_succeeds(self, mock_admin_user):
        """AC-05: Update role_name/quota_config/remark."""
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Old Name", role_type="tenant")
        req = RoleUpdateRequest(role_name="New Name")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.update_role = AsyncMock(return_value=role)
            mock_qs.validate_quota_config = MagicMock()

            result = await RoleService.update_role(
                role_id=15,
                req=req,
                login_user=mock_admin_user,
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_update_role_checks_duplicate_name_in_target_department_scope(self, mock_admin_user):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Old Name", role_type="tenant", department_id=5)
        req = RoleUpdateRequest(role_name="New Name", department_id=8)

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
            patch.object(RoleService, "_validate_department", new_callable=AsyncMock),
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.update_role = AsyncMock(return_value=role)
            mock_qs.validate_quota_config = MagicMock()

            await RoleService.update_role(
                role_id=15,
                req=req,
                login_user=mock_admin_user,
            )

        RoleDefinitionRepository.update.assert_awaited_once_with(
            role, {"role_name": "New Name", "department_id": 8}, operator_id=mock_admin_user.user_id
        )

    @pytest.mark.asyncio
    async def test_update_role_checks_duplicate_name_when_clearing_scope_to_global(self, mock_admin_user):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Scoped Name", role_type="tenant", department_id=5)
        req = RoleUpdateRequest(role_name="Global Name", department_id=None)

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch("bisheng.role.domain.services.role_service.QuotaService") as mock_qs,
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.aget_role_by_name = AsyncMock(return_value=None)
            mock_dao.update_role = AsyncMock(return_value=role)
            mock_qs.validate_quota_config = MagicMock()

            await RoleService.update_role(
                role_id=15,
                req=req,
                login_user=mock_admin_user,
            )

        RoleDefinitionRepository.update.assert_awaited_once_with(
            role, {"role_name": "Global Name", "department_id": None}, operator_id=mock_admin_user.user_id
        )
        assert role.department_id is None

    @pytest.mark.asyncio
    async def test_tenant_admin_cannot_update_global(self, mock_tenant_admin):
        """AC-06: Tenant admin updating global role → 24003."""
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(2, "Default", role_type="global")
        req = RoleUpdateRequest(remark="hacked")

        with patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao:
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=2,
                    req=req,
                    login_user=mock_tenant_admin,
                )

    @pytest.mark.asyncio
    async def test_dept_admin_cannot_update_role_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(18, "Tenant Role", role_type="tenant", department_id=99)
        req = RoleUpdateRequest(remark="nope")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="dept_admin"),
            patch.object(RoleService, "_get_dept_subtree_ids", new_callable=AsyncMock, return_value=[5, 6]),
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)

            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_role(
                    role_id=18,
                    req=req,
                    login_user=mock_dept_admin,
                )

    @pytest.mark.asyncio
    async def test_tenant_admin_can_update_tenant_role_created_by_other_admin(self, mock_tenant_admin):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(16, "Editable?", role_type="tenant")
        req = RoleUpdateRequest(remark="attempt")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="tenant_admin"),
            patch.object(RoleService, "_get_role_creator_ids", new_callable=AsyncMock, return_value={16: 998}),
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.update_role = AsyncMock(return_value=role)

            await RoleService.update_role(
                role_id=16,
                req=req,
                login_user=mock_tenant_admin,
            )

        RoleDefinitionRepository.update.assert_awaited_once_with(
            role, {"remark": "attempt"}, operator_id=mock_tenant_admin.user_id
        )

    @pytest.mark.asyncio
    async def test_tenant_admin_can_update_missing_creator_legacy_role(self, mock_tenant_admin):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(17, "Legacy Role", role_type="tenant")
        req = RoleUpdateRequest(remark="attempt")

        with (
            patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
            patch.object(RoleService, "_check_role_permission", new_callable=AsyncMock),
            patch.object(RoleService, "_get_permission_level", new_callable=AsyncMock, return_value="tenant_admin"),
            patch.object(RoleService, "_get_role_creator_ids", new_callable=AsyncMock, return_value={}),
        ):
            mock_dao.aget_role_by_id = AsyncMock(return_value=role)
            mock_dao.update_role = AsyncMock(return_value=role)

            await RoleService.update_role(
                role_id=17,
                req=req,
                login_user=mock_tenant_admin,
            )

        RoleDefinitionRepository.update.assert_awaited_once_with(
            role, {"remark": "attempt"}, operator_id=mock_tenant_admin.user_id
        )


class TestMenuPermissions:
    """The service normalizes menus and delegates one owner transaction."""

    @pytest.mark.parametrize("entry", ["update_menu", "update_role_with_menu"])
    async def test_menu_save_uses_definition_transaction(self, mock_admin_user, entry):
        from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15, "Test")
        with (
            patch.object(RoleService, "_check_role_permission", AsyncMock()),
            patch.object(RoleService, "_ensure_role_mutation_access", AsyncMock()),
            patch("bisheng.role.domain.services.role_service.RoleDao.aget_role_by_id", AsyncMock(return_value=role)),
        ):
            if entry == "update_menu":
                await RoleService.update_menu(15, ["build", "build", "system_config"], mock_admin_user)
                RoleDefinitionRepository.update.assert_awaited_once_with(role, {}, ["build"])
            else:
                await RoleService.update_role_with_menu(
                    15, RoleUpdateRequest(menu_ids=["build", "build"]), mock_admin_user
                )
                RoleDefinitionRepository.update.assert_awaited_once_with(role, {}, ["build"], operator_id=1)

    async def test_get_menu(self, mock_admin_user, definition_store):
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(15)
        definition_store.menu.return_value = [MagicMock(third_id="build"), MagicMock(third_id="system_config")]
        with (
            patch.object(RoleService, "_check_role_permission", AsyncMock()),
            patch.object(RoleService, "_ensure_role_scope_access", AsyncMock()),
            patch("bisheng.role.domain.services.role_service.RoleDao.aget_role_by_id", AsyncMock(return_value=role)),
        ):
            assert await RoleService.get_menu(15, mock_admin_user) == ["build"]
        definition_store.menu.assert_awaited_once_with(role)

    async def test_dept_admin_cannot_update_menu_outside_subtree(self, mock_dept_admin):
        from bisheng.common.errcode.role import RolePermissionDeniedError
        from bisheng.role.domain.services.role_service import RoleService

        role = _make_role(22, department_id=99)
        with (
            patch.object(RoleService, "_check_role_permission", AsyncMock()),
            patch.object(RoleService, "_get_permission_level", AsyncMock(return_value="dept_admin")),
            patch.object(RoleService, "_get_dept_subtree_ids", AsyncMock(return_value=[5, 6])),
            patch("bisheng.role.domain.services.role_service.RoleDao.aget_role_by_id", AsyncMock(return_value=role)),
        ):
            with pytest.raises(RolePermissionDeniedError):
                await RoleService.update_menu(22, ["build"], mock_dept_admin)
        RoleDefinitionRepository.update.assert_not_awaited()

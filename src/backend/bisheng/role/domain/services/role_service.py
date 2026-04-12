"""RoleService — role CRUD, menu permissions, permission checks (F005).

Four-level permission check for role management:
  1. System admin → full access
  2. Tenant admin → tenant roles read/write, global roles read-only
  3. Department admin → dept subtree roles only, global read-only
  4. Regular user → denied (24003)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from bisheng.common.errcode.role import (
    RoleBuiltinProtectedError,
    RoleNameDuplicateError,
    RoleNotFoundError,
    RolePermissionDeniedError,
)
from bisheng.database.models.role import Role, RoleDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.role.domain.schemas.role_schema import (
    RoleCreateRequest,
    RoleListResponse,
    RoleUpdateRequest,
)
from bisheng.role.domain.services.quota_service import QuotaService

logger = logging.getLogger(__name__)

# Built-in roles that cannot be deleted (AdminRole=1, DefaultRole=2)
BUILTIN_ROLE_IDS = {1, 2}


class RoleService:
    """Stateless service for role CRUD operations."""

    # ── Create ──

    @classmethod
    async def create_role(
        cls,
        req: RoleCreateRequest,
        login_user,
    ) -> Role:
        """Create a new role (AC-01, AC-02).

        System admin creates global role; tenant admin creates tenant role.
        """
        await cls._check_role_permission(login_user)

        # Validate quota_config (AC-10c)
        if req.quota_config:
            QuotaService.validate_quota_config(req.quota_config)

        # Determine role_type
        role_type = 'global' if login_user.is_admin() else 'tenant'

        # Check duplicate name (AC-09)
        existing = await RoleDao.aget_role_by_name(
            tenant_id=login_user.tenant_id,
            role_type=role_type,
            role_name=req.role_name,
        )
        if existing:
            raise RoleNameDuplicateError()

        # Validate department_id if provided
        if req.department_id is not None:
            await cls._validate_department(req.department_id)

        role = Role(
            role_name=req.role_name,
            role_type=role_type,
            department_id=req.department_id,
            quota_config=req.quota_config,
            remark=req.remark,
        )
        return await RoleDao.ainsert_role(role)

    # ── List ──

    @classmethod
    async def list_roles(
        cls,
        keyword: Optional[str],
        page: int,
        limit: int,
        login_user,
    ) -> dict:
        """List visible roles with pagination (AC-03, AC-04, AC-04b).

        Returns {data: List[RoleListResponse], total: int}.
        """
        department_ids = None
        permission_level = 'admin'

        if not login_user.is_admin():
            permission_level = await cls._check_list_permission(login_user)
            if permission_level == 'dept_admin':
                department_ids = await cls._get_dept_subtree_ids(login_user)

        roles = await RoleDao.aget_visible_roles(
            tenant_id=login_user.tenant_id,
            keyword=keyword,
            page=page,
            limit=limit,
            department_ids=department_ids,
        )
        total = await RoleDao.acount_visible_roles(
            tenant_id=login_user.tenant_id,
            keyword=keyword,
            department_ids=department_ids,
        )

        # Get user counts
        role_ids = [r.id for r in roles]
        user_counts = await RoleDao.aget_user_count_by_role_ids(role_ids)

        # Get department names
        dept_names = await cls._get_department_names(roles)

        # Build response
        items = []
        for role in roles:
            is_readonly = cls._is_readonly(role, login_user, permission_level)
            items.append(RoleListResponse(
                id=role.id,
                role_name=role.role_name,
                role_type=role.role_type,
                department_id=role.department_id,
                department_name=dept_names.get(role.department_id),
                quota_config=role.quota_config,
                remark=role.remark,
                user_count=user_counts.get(role.id, 0),
                is_readonly=is_readonly,
                create_time=role.create_time,
                update_time=role.update_time,
            ))

        return {'data': items, 'total': total}

    # ── Get ──

    @classmethod
    async def get_role(
        cls,
        role_id: int,
        login_user,
    ) -> RoleListResponse:
        """Get role detail (AC-10)."""
        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        user_counts = await RoleDao.aget_user_count_by_role_ids([role_id])
        dept_names = await cls._get_department_names([role])

        permission_level = 'admin' if login_user.is_admin() else 'tenant_admin'
        is_readonly = cls._is_readonly(role, login_user, permission_level)

        return RoleListResponse(
            id=role.id,
            role_name=role.role_name,
            role_type=role.role_type,
            department_id=role.department_id,
            department_name=dept_names.get(role.department_id),
            quota_config=role.quota_config,
            remark=role.remark,
            user_count=user_counts.get(role.id, 0),
            is_readonly=is_readonly,
            create_time=role.create_time,
            update_time=role.update_time,
        )

    # ── Update ──

    @classmethod
    async def update_role(
        cls,
        role_id: int,
        req: RoleUpdateRequest,
        login_user,
    ) -> Role:
        """Update role (AC-05, AC-06)."""
        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        # AC-06: tenant admin cannot update global role
        if not login_user.is_admin() and role.role_type == 'global':
            raise RolePermissionDeniedError(msg='Cannot modify global role')

        await cls._check_role_permission(login_user)

        # Validate quota_config (AC-10c)
        if req.quota_config is not None:
            QuotaService.validate_quota_config(req.quota_config)

        # Check duplicate name if changing name (AC-09)
        if req.role_name and req.role_name != role.role_name:
            existing = await RoleDao.aget_role_by_name(
                tenant_id=login_user.tenant_id,
                role_type=role.role_type,
                role_name=req.role_name,
            )
            if existing and existing.id != role_id:
                raise RoleNameDuplicateError()

        # Validate department_id if provided
        if req.department_id is not None:
            await cls._validate_department(req.department_id)

        # Apply updates
        if req.role_name is not None:
            role.role_name = req.role_name
        if req.quota_config is not None:
            role.quota_config = req.quota_config
        if req.remark is not None:
            role.remark = req.remark
        if req.department_id is not None:
            role.department_id = req.department_id

        return await RoleDao.update_role(role)

    # ── Delete ──

    @classmethod
    async def delete_role(
        cls,
        role_id: int,
        login_user,
    ) -> None:
        """Delete role with cascade (AC-07, AC-08)."""
        # AC-07: Builtin protection
        if role_id in BUILTIN_ROLE_IDS:
            raise RoleBuiltinProtectedError()

        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        # Permission check (AC-06 equivalent)
        if not login_user.is_admin() and role.role_type == 'global':
            raise RolePermissionDeniedError(msg='Cannot delete global role')

        await cls._check_role_permission(login_user)

        # AC-08: Cascade delete (UserRole + RoleAccess handled in DAO)
        await RoleDao.adelete_role(role_id)

    # ── Menu permissions ──

    @classmethod
    async def update_menu(
        cls,
        role_id: int,
        menu_ids: List[str],
        login_user,
    ) -> None:
        """Update role menu permissions (AC-11)."""
        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        if not login_user.is_admin() and role.role_type == 'global':
            raise RolePermissionDeniedError(msg='Cannot modify global role menu')

        await cls._check_role_permission(login_user)

        await RoleAccessDao.update_role_access_all(
            role_id=role_id,
            access_type=AccessType.WEB_MENU,
            access_ids=menu_ids,
        )

    @classmethod
    async def get_menu(
        cls,
        role_id: int,
        login_user,
    ) -> List[str]:
        """Get role menu permissions (AC-12)."""
        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        records = await RoleAccessDao.aget_role_access(
            role_ids=[role_id],
            access_type=AccessType.WEB_MENU,
        )
        return [r.third_id for r in records]

    # ── Permission helpers ──

    @classmethod
    async def _check_role_permission(cls, login_user) -> None:
        """Four-level permission check for role management (AC-10b).

        1. System admin → allowed
        2. Tenant admin → allowed
        3. Department admin → allowed (scope enforced in DAO)
        4. Regular user → denied
        """
        if login_user.is_admin():
            return

        # Check tenant admin via PermissionService
        try:
            from bisheng.permission.domain.services.permission_service import PermissionService
            is_tenant_admin = await PermissionService.check(
                user_id=login_user.user_id,
                relation='admin',
                object_type='tenant',
                object_id=str(login_user.tenant_id),
                login_user=login_user,
            )
            if is_tenant_admin:
                return
        except Exception:
            pass

        # Check department admin
        try:
            dept_ids = await cls._get_user_admin_dept_ids(login_user)
            if dept_ids:
                return
        except Exception:
            pass

        raise RolePermissionDeniedError()

    @classmethod
    async def _check_list_permission(cls, login_user) -> str:
        """Check permission level for list operation.

        Returns: 'admin', 'tenant_admin', 'dept_admin', or raises.
        """
        if login_user.is_admin():
            return 'admin'

        try:
            from bisheng.permission.domain.services.permission_service import PermissionService
            is_tenant_admin = await PermissionService.check(
                user_id=login_user.user_id,
                relation='admin',
                object_type='tenant',
                object_id=str(login_user.tenant_id),
                login_user=login_user,
            )
            if is_tenant_admin:
                return 'tenant_admin'
        except Exception:
            pass

        dept_ids = await cls._get_user_admin_dept_ids(login_user)
        if dept_ids:
            return 'dept_admin'

        # Regular users can still view the list (read-only)
        return 'regular'

    @classmethod
    def _is_readonly(cls, role, login_user, permission_level: str) -> bool:
        """Determine if role is read-only for current user."""
        if permission_level == 'admin':
            return False  # System admin can edit all
        if role.role_type == 'global':
            return True  # Global roles are read-only for non-system-admins
        if permission_level == 'regular':
            return True
        return False

    @classmethod
    async def _get_user_admin_dept_ids(cls, login_user) -> List[int]:
        """Get department IDs where user is admin."""
        try:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
            return [d.id for d in depts] if depts else []
        except Exception:
            return []

    @classmethod
    async def _get_dept_subtree_ids(cls, login_user) -> Optional[List[int]]:
        """Get department subtree IDs for department admin filtering."""
        try:
            from bisheng.database.models.department import DepartmentDao
            admin_depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
            if not admin_depts:
                return None
            all_ids = set()
            for dept in admin_depts:
                subtree = await DepartmentDao.aget_subtree_ids(dept.path)
                all_ids.update(subtree)
            return list(all_ids)
        except Exception:
            return None

    @classmethod
    async def _get_department_names(cls, roles) -> dict:
        """Get department names for roles with department_id."""
        dept_ids = [r.department_id for r in roles if r.department_id]
        if not dept_ids:
            return {}
        try:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_by_ids(list(set(dept_ids)))
            return {d.id: d.name for d in depts} if depts else {}
        except Exception:
            return {}

    @classmethod
    async def _validate_department(cls, department_id: int) -> None:
        """Validate department_id exists and is active."""
        from bisheng.common.errcode.role import QuotaConfigInvalidError
        try:
            from bisheng.database.models.department import DepartmentDao
            dept = await DepartmentDao.aget_by_id(department_id)
            if not dept or dept.status != 'active':
                raise QuotaConfigInvalidError(msg=f'Department {department_id} not found or inactive')
        except QuotaConfigInvalidError:
            raise
        except Exception as e:
            logger.warning('Failed to validate department %d: %s', department_id, e)

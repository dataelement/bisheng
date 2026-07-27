from __future__ import annotations

from bisheng.database.constants import AdminRole
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.role import RoleDao
from bisheng.permission.domain.services.legacy_rbac_sync_service import (
    LegacyRBACSyncService,
)
from bisheng.user.domain.models.user_role import UserRoleDao


class DepartmentSyncRBACService:
    """同步入口使用的部门范围角色维护服务。"""

    @classmethod
    async def arevoke_user_roles_in_department(
        cls,
        user_id: int,
        department_id: int,
    ) -> None:
        old_role_ids = {
            int(row.role_id) for row in await UserRoleDao.aget_user_roles(user_id) if row.role_id is not None
        }
        if not old_role_ids:
            return

        role_rows = await RoleDao.aget_role_by_ids(list(old_role_ids))
        revoke_role_ids = {
            int(role.id)
            for role in role_rows
            if role.id is not None
            and int(role.id) != AdminRole
            and int(getattr(role, "department_id", 0) or 0) == int(department_id)
        }
        if not revoke_role_ids:
            return

        UserRoleDao.delete_user_roles(user_id, sorted(revoke_role_ids))
        await LegacyRBACSyncService.sync_user_role_change(
            user_id,
            old_role_ids,
            old_role_ids - revoke_role_ids,
        )

    @classmethod
    async def aapply_department_default_roles_for_user(
        cls,
        user_id: int,
        department_id: int,
    ) -> None:
        department = await DepartmentDao.aget_by_id(department_id)
        if department is None or getattr(department, "status", "active") != "active":
            return

        configured_role_ids = {
            int(role_id)
            for role_id in (getattr(department, "default_role_ids", None) or [])
            if role_id is not None and int(role_id) != AdminRole
        }
        if not configured_role_ids:
            return

        role_rows = await RoleDao.aget_role_by_ids(list(configured_role_ids))
        allowed_scope_ids = {
            int(part) for part in str(getattr(department, "path", "") or "").split("/") if part.isdigit()
        }
        allowed_scope_ids.add(int(department_id))
        valid_role_ids = {
            int(role.id)
            for role in role_rows
            if role.id is not None
            and int(role.id) != AdminRole
            and (getattr(role, "department_id", None) is None or int(role.department_id) in allowed_scope_ids)
        }
        if not valid_role_ids:
            return

        old_role_ids = {
            int(row.role_id) for row in await UserRoleDao.aget_user_roles(user_id) if row.role_id is not None
        }
        add_role_ids = valid_role_ids - old_role_ids
        if not add_role_ids:
            return

        UserRoleDao.add_user_roles(user_id, sorted(add_role_ids))
        await LegacyRBACSyncService.sync_user_role_change(
            user_id,
            old_role_ids,
            old_role_ids | add_role_ids,
        )

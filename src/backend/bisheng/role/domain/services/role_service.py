"""RoleService — role CRUD, menu permissions, permission checks (F005).

Four-level permission check for role management:
  1. System admin → full access
  2. Tenant admin → tenant roles read/write; role list hides global (non-manageable) rows
  3. Department admin → list shows global presets (read-only) + tenant roles in managed subtree
     or global scope; update/delete are restricted to the role creator
  4. Regular user → denied (24003)
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import List, Optional

from sqlmodel import delete, select

from bisheng.common.errcode.role import (
    RoleBuiltinProtectedError,
    RoleNameDuplicateError,
    RoleNotFoundError,
    RolePermissionDeniedError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.role import Role, RoleDao
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleAccessDao
from bisheng.role.domain.schemas.role_schema import (
    RoleCreateRequest,
    RoleListResponse,
    RoleUpdateRequest,
)
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.user.domain.models.user import UserDao

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
            department_id=req.department_id,
        )
        if existing:
            raise RoleNameDuplicateError()

        # Validate department_id if provided
        if req.department_id is not None:
            await cls._validate_department(req.department_id)

        await cls._ensure_create_scope(login_user, req.department_id)

        role = Role(
            role_name=req.role_name,
            role_type=role_type,
            department_id=req.department_id,
            quota_config=req.quota_config,
            remark=req.remark,
            create_user=login_user.user_id,
        )
        try:
            return await RoleDao.ainsert_role(role)
        except Exception as e:
            if 'Duplicate entry' in str(e) or 'IntegrityError' in type(e).__name__:
                raise RoleNameDuplicateError()
            raise

    @classmethod
    async def create_role_with_menu(
        cls,
        req: RoleCreateRequest,
        login_user,
    ) -> Role:
        await cls._check_role_permission(login_user)

        if req.quota_config:
            QuotaService.validate_quota_config(req.quota_config)

        role_type = 'global' if login_user.is_admin() else 'tenant'
        existing = await RoleDao.aget_role_by_name(
            tenant_id=login_user.tenant_id,
            role_type=role_type,
            role_name=req.role_name,
            department_id=req.department_id,
        )
        if existing:
            raise RoleNameDuplicateError()

        if req.department_id is not None:
            await cls._validate_department(req.department_id)

        await cls._ensure_create_scope(login_user, req.department_id)

        menu_ids = cls._normalize_menu_ids(req.menu_ids or [])
        role = Role(
            role_name=req.role_name,
            role_type=role_type,
            department_id=req.department_id,
            quota_config=req.quota_config,
            remark=req.remark,
            create_user=login_user.user_id,
        )

        async with get_async_db_session() as session:
            session.add(role)
            await session.flush()
            await cls._replace_menu_access_in_session(session, role.id, menu_ids)
            await session.commit()
            await session.refresh(role)

        return role

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
        dept_subtree_ids: set[int] | None = None
        tenant_custom_roles_only = False

        if not login_user.is_admin():
            from bisheng.database.models.department import DepartmentDao

            try:
                admin_depts = await DepartmentDao.aget_user_admin_departments(
                    login_user.user_id,
                )
            except Exception:
                logger.exception(
                    'list_roles: aget_user_admin_departments failed user=%s',
                    getattr(login_user, 'user_id', None),
                )
                admin_depts = []

            if admin_depts:
                permission_level = 'dept_admin'
                subtree_ids: set[int] = set()
                for d in admin_depts:
                    path = getattr(d, 'path', None) or ''
                    if not path:
                        if getattr(d, 'id', None):
                            subtree_ids.add(int(d.id))
                        continue
                    try:
                        rows = await DepartmentDao.aget_subtree_ids(path)
                    except Exception:
                        logger.exception(
                            'list_roles: aget_subtree_ids failed path=%s', path,
                        )
                        rows = []
                    for row in rows or []:
                        if isinstance(row, (list, tuple)):
                            subtree_ids.add(int(row[0]))
                        else:
                            subtree_ids.add(int(row))
                if not subtree_ids:
                    subtree_ids = {int(d.id) for d in admin_depts if getattr(d, 'id', None)}
                department_ids = list(subtree_ids)
                dept_subtree_ids = subtree_ids
            else:
                try:
                    from bisheng.permission.domain.services.permission_service import (
                        PermissionService,
                    )
                    is_tenant_admin = await PermissionService.check(
                        user_id=login_user.user_id,
                        relation='admin',
                        object_type='tenant',
                        object_id=str(login_user.tenant_id),
                        login_user=login_user,
                    )
                except Exception:
                    logger.exception(
                        'list_roles: tenant admin check failed user=%s',
                        getattr(login_user, 'user_id', None),
                    )
                    is_tenant_admin = False
                if is_tenant_admin:
                    permission_level = 'tenant_admin'
                    tenant_custom_roles_only = True
                else:
                    permission_level = 'regular'

        roles = await RoleDao.aget_visible_roles(
            tenant_id=login_user.tenant_id,
            keyword=keyword,
            page=page,
            limit=limit,
            department_ids=department_ids,
            tenant_custom_roles_only=tenant_custom_roles_only,
        )
        total = await RoleDao.acount_visible_roles(
            tenant_id=login_user.tenant_id,
            keyword=keyword,
            department_ids=department_ids,
            tenant_custom_roles_only=tenant_custom_roles_only,
        )

        # Get user counts
        role_ids = [r.id for r in roles]
        user_counts = await RoleDao.aget_user_count_by_role_ids(role_ids)

        # Get department names + full scope path (root → leaf)
        dept_names = await cls._get_department_names(roles)
        scope_paths = await cls._department_scope_paths_for_roles(roles)
        creator_ids = await cls._get_role_creator_ids(roles)
        creator_names = await cls._get_creator_names(creator_ids)

        # Build response
        items = []
        for role in roles:
            is_readonly = cls._is_readonly(
                role,
                login_user,
                permission_level,
                dept_subtree_ids,
                creator_user_id=creator_ids.get(role.id),
            )
            items.append(RoleListResponse(
                id=role.id,
                role_name=role.role_name,
                role_type=role.role_type,
                department_id=role.department_id,
                department_name=dept_names.get(role.department_id),
                department_scope_path=scope_paths.get(role.department_id) if role.department_id else None,
                quota_config=role.quota_config,
                remark=role.remark,
                user_count=user_counts.get(role.id, 0),
                creator_name=creator_names.get(role.id),
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
        """Get role detail (AC-10). Requires at least admin/tenant-admin/dept-admin."""
        await cls._check_role_permission(login_user)

        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        await cls._ensure_role_scope_access(
            role, login_user, for_mutation=False,
        )

        user_counts = await RoleDao.aget_user_count_by_role_ids([role_id])
        dept_names = await cls._get_department_names([role])
        scope_paths = await cls._department_scope_paths_for_roles([role])
        creator_ids = await cls._get_role_creator_ids([role])
        creator_names = await cls._get_creator_names(creator_ids)

        permission_level = await cls._get_permission_level(login_user)
        dept_subtree_ids = None
        if permission_level == 'dept_admin':
            dept_subtree_ids = set(await cls._get_dept_subtree_ids(login_user) or [])
        is_readonly = cls._is_readonly(
            role,
            login_user,
            permission_level,
            dept_subtree_ids,
            creator_user_id=creator_ids.get(role.id),
        )

        return RoleListResponse(
            id=role.id,
            role_name=role.role_name,
            role_type=role.role_type,
            department_id=role.department_id,
            department_name=dept_names.get(role.department_id),
            department_scope_path=scope_paths.get(role.department_id) if role.department_id else None,
            quota_config=role.quota_config,
            remark=role.remark,
            user_count=user_counts.get(role.id, 0),
            creator_name=creator_names.get(role.id),
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
        await cls._ensure_role_mutation_access(role, login_user)

        # Validate quota_config (AC-10c)
        if req.quota_config is not None:
            QuotaService.validate_quota_config(req.quota_config)

        # Check duplicate name if changing name (AC-09)
        if req.role_name and req.role_name != role.role_name:
            target_department_id = req.department_id if 'department_id' in req.model_fields_set else role.department_id
            existing = await RoleDao.aget_role_by_name(
                tenant_id=login_user.tenant_id,
                role_type=role.role_type,
                role_name=req.role_name,
                department_id=target_department_id,
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
        # 允许显式清空为全局作用域（null）；不能仅用 ``is not None`` 否则无法从部门改回全局
        if 'department_id' in req.model_fields_set:
            role.department_id = req.department_id

        return await RoleDao.update_role(role)

    @classmethod
    async def update_role_with_menu(
        cls,
        role_id: int,
        req: RoleUpdateRequest,
        login_user,
    ) -> Role:
        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        if not login_user.is_admin() and role.role_type == 'global':
            raise RolePermissionDeniedError(msg='Cannot modify global role')

        await cls._check_role_permission(login_user)
        await cls._ensure_role_mutation_access(role, login_user)

        if req.quota_config is not None:
            QuotaService.validate_quota_config(req.quota_config)

        if req.role_name and req.role_name != role.role_name:
            target_department_id = req.department_id if 'department_id' in req.model_fields_set else role.department_id
            existing = await RoleDao.aget_role_by_name(
                tenant_id=login_user.tenant_id,
                role_type=role.role_type,
                role_name=req.role_name,
                department_id=target_department_id,
            )
            if existing and existing.id != role_id:
                raise RoleNameDuplicateError()

        if req.department_id is not None:
            await cls._validate_department(req.department_id)

        menu_ids = cls._normalize_menu_ids(req.menu_ids or [])

        async with get_async_db_session() as session:
            result = await session.exec(select(Role).where(Role.id == role_id))
            db_role = result.first()
            if not db_role:
                raise RoleNotFoundError()

            if req.role_name is not None:
                db_role.role_name = req.role_name
            if req.quota_config is not None:
                db_role.quota_config = req.quota_config
            if req.remark is not None:
                db_role.remark = req.remark
            if 'department_id' in req.model_fields_set:
                db_role.department_id = req.department_id
            # Touch the role row so menu-only edits also refresh update_time.
            db_role.update_time = datetime.now()

            session.add(db_role)
            await cls._replace_menu_access_in_session(session, role_id, menu_ids)
            await session.commit()
            await session.refresh(db_role)
            return db_role

    # ── Delete ──

    @classmethod
    async def delete_role(
        cls,
        role_id: int,
        login_user,
    ) -> Role:
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
        await cls._ensure_role_mutation_access(role, login_user)

        # AC-08: Cascade delete (UserRole + RoleAccess handled in DAO)
        await RoleDao.adelete_role(role_id)
        return role

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
        await cls._ensure_role_mutation_access(role, login_user)

        normalized = cls._normalize_menu_ids(menu_ids)
        async with get_async_db_session() as session:
            result = await session.exec(select(Role).where(Role.id == role_id))
            db_role = result.first()
            if not db_role:
                raise RoleNotFoundError()
            # Touch the role row so pure menu edits bump update_time in the list.
            db_role.update_time = datetime.now()
            session.add(db_role)
            await cls._replace_menu_access_in_session(session, role_id, normalized)
            await session.commit()
            await session.refresh(db_role)

    @classmethod
    async def get_menu(
        cls,
        role_id: int,
        login_user,
    ) -> List[str]:
        """Get role menu permissions (AC-12). Requires admin/tenant-admin/dept-admin."""
        await cls._check_role_permission(login_user)

        role = await RoleDao.aget_role_by_id(role_id)
        if not role:
            raise RoleNotFoundError()

        await cls._ensure_role_scope_access(
            role, login_user, for_mutation=False,
        )

        records = await RoleAccessDao.aget_role_access(
            role_ids=[role_id],
            access_type=AccessType.WEB_MENU,
        )
        # system_config 仅超管/部门管理员通过身份下发，不可通过自定义角色分配
        return [r.third_id for r in records if r.third_id != 'system_config']

    # ── Permission helpers ──

    @classmethod
    async def _get_permission_level(cls, login_user) -> str:
        """Determine user's permission level for role management.

        Returns: 'admin', 'tenant_admin', 'dept_admin', or 'regular'.

        **部门管理员优先于租户管理员**：若先判 ``tenant:admin``，则兼任部门管理员的账号
        会拿到租户级角色列表（全租户自定义角色可编辑），与「按部门子树管理角色」PRD 冲突。
        """
        if login_user.is_admin():
            return 'admin'

        dept_ids = await cls._get_user_admin_dept_ids(login_user)
        if dept_ids:
            return 'dept_admin'

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
        except Exception as e:
            logger.warning('PermissionService.check failed for user %d: %s', login_user.user_id, e)

        return 'regular'

    @classmethod
    async def _check_role_permission(cls, login_user) -> None:
        """Four-level permission check for role management (AC-10b).

        Raises RolePermissionDeniedError for regular users.
        """
        level = await cls._get_permission_level(login_user)
        if level == 'regular':
            raise RolePermissionDeniedError()

    @classmethod
    async def _check_list_permission(cls, login_user) -> str:
        """Check permission level for list operation. Alias for _get_permission_level."""
        return await cls._get_permission_level(login_user)

    @classmethod
    def _is_readonly(
        cls,
        role,
        login_user,
        permission_level: str,
        dept_subtree_ids: Optional[set[int]] = None,
        creator_user_id: Optional[int] = None,
    ) -> bool:
        """Determine if role is read-only for current user."""
        if permission_level == 'regular':
            return True
        return not cls._can_mutate_role(
            role,
            login_user,
            permission_level,
            dept_subtree_ids=dept_subtree_ids,
            creator_user_id=creator_user_id,
        )

    @classmethod
    def _can_mutate_role(
        cls,
        role,
        login_user,
        permission_level: str,
        dept_subtree_ids: Optional[set[int]] = None,
        creator_user_id: Optional[int] = None,
    ) -> bool:
        if permission_level == 'regular':
            return False
        if role.role_type == 'global' and not login_user.is_admin():
            return False
        if permission_level == 'dept_admin' and role.department_id is not None:
            if dept_subtree_ids is None or role.department_id not in dept_subtree_ids:
                return False
        if creator_user_id is None:
            return cls._can_mutate_role_without_creator(
                role,
                permission_level,
                dept_subtree_ids=dept_subtree_ids,
            )
        return int(creator_user_id) == int(login_user.user_id)

    @classmethod
    def _can_mutate_role_without_creator(
        cls,
        role,
        permission_level: str,
        dept_subtree_ids: Optional[set[int]] = None,
    ) -> bool:
        # Missing creator metadata is treated as readonly for non-admins.
        return permission_level == 'admin'

    @classmethod
    async def _get_user_admin_dept_ids(cls, login_user) -> List[int]:
        """Get department IDs where user is admin."""
        try:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
            return [int(d.id) for d in depts] if depts else []
        except Exception:
            logger.exception(
                'Failed to query admin departments for user %s',
                getattr(login_user, 'user_id', None),
            )
            return []

    @classmethod
    async def _get_dept_subtree_ids(cls, login_user) -> Optional[List[int]]:
        """Get department subtree IDs for department admin filtering."""
        try:
            from bisheng.database.models.department import DepartmentDao
            admin_depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
            if not admin_depts:
                return None
            all_ids: set[int] = set()
            for dept in admin_depts:
                path = getattr(dept, 'path', None) or ''
                if not path:
                    continue
                subtree = await DepartmentDao.aget_subtree_ids(path)
                for row in subtree or []:
                    if isinstance(row, (list, tuple)):
                        all_ids.add(int(row[0]))
                    else:
                        all_ids.add(int(row))
            return list(all_ids)
        except Exception:
            logger.exception(
                'Failed to query dept subtree for user %s',
                getattr(login_user, 'user_id', None),
            )
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
        except Exception as e:
            logger.debug('Failed to query department names: %s', e)
            return {}

    @classmethod
    async def _department_scope_paths_for_roles(cls, roles) -> dict:
        """Full path labels ``根 / … / 作用域部门`` from ``Department.path`` (not UI-trimmed tree)."""
        dept_ids = [int(r.department_id) for r in roles if r.department_id]
        unique = sorted(set(dept_ids))
        if not unique:
            return {}
        try:
            from bisheng.database.models.department import DepartmentDao
            depts = await DepartmentDao.aget_by_ids(unique)
            if not depts:
                return {}
            seg_ids: set[int] = set()
            for d in depts:
                for seg in (getattr(d, 'path', None) or '').strip('/').split('/'):
                    if seg.isdigit():
                        seg_ids.add(int(seg))
            id_to_name = {d.id: d.name for d in depts}
            missing = seg_ids - set(id_to_name.keys())
            if missing:
                extra = await DepartmentDao.aget_by_ids(list(missing))
                for d in extra or []:
                    id_to_name[d.id] = d.name
            out: dict = {}
            for d in depts:
                ids = [
                    int(s) for s in (getattr(d, 'path', None) or '').strip('/').split('/')
                    if s.isdigit()
                ]
                parts = [id_to_name.get(i) for i in ids if id_to_name.get(i)]
                out[d.id] = ' / '.join(parts) if parts else (d.name or '')
            return out
        except Exception as e:
            logger.debug('Failed to build department scope paths: %s', e)
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

    @classmethod
    def _normalize_menu_ids(cls, menu_ids: List[str]) -> List[str]:
        """Deduplicate menu keys; strip system_config (reserved for super-admin / dept-admin)."""
        out: list[str] = []
        for menu_id in menu_ids:
            s = str(menu_id)
            if s == 'system_config':
                continue
            if s not in out:
                out.append(s)
        return out

    @classmethod
    async def _replace_menu_access_in_session(
        cls, session, role_id: int, menu_ids: List[str],
    ) -> None:
        await session.exec(
            delete(RoleAccess).where(
                RoleAccess.role_id == role_id,
                RoleAccess.type == AccessType.WEB_MENU.value,
            ),
        )
        for menu_id in menu_ids:
            session.add(RoleAccess(
                role_id=role_id,
                third_id=menu_id,
                type=AccessType.WEB_MENU.value,
            ))

    @classmethod
    async def _ensure_create_scope(
        cls, login_user, department_id: Optional[int],
    ) -> None:
        """Department admins may only create roles inside their managed subtree."""
        permission_level = await cls._get_permission_level(login_user)
        if permission_level != 'dept_admin':
            return

        subtree_ids = set(await cls._get_dept_subtree_ids(login_user) or [])
        if department_id is None or department_id not in subtree_ids:
            raise RolePermissionDeniedError(
                msg='Department admin may only create roles within managed departments',
            )

    @classmethod
    async def _ensure_role_scope_access(
        cls, role, login_user, for_mutation: bool,
    ) -> None:
        """Department admins may only view global/global-scope roles or subtree roles."""
        permission_level = await cls._get_permission_level(login_user)
        if permission_level != 'dept_admin':
            return

        subtree_ids = set(await cls._get_dept_subtree_ids(login_user) or [])
        if for_mutation:
            if role.department_id is not None and role.department_id in subtree_ids:
                return
        else:
            if role.role_type == 'global' or role.department_id is None or role.department_id in subtree_ids:
                return

        action = 'modify' if for_mutation else 'view'
        raise RolePermissionDeniedError(
            msg=f'Department admin cannot {action} roles outside managed departments',
        )

    @classmethod
    async def _ensure_role_mutation_access(cls, role, login_user) -> None:
        permission_level = await cls._get_permission_level(login_user)
        dept_subtree_ids = None
        if permission_level == 'dept_admin':
            dept_subtree_ids = set(await cls._get_dept_subtree_ids(login_user) or [])

        creator_ids = await cls._get_role_creator_ids([role])
        creator_user_id = creator_ids.get(role.id)
        if cls._can_mutate_role(
            role,
            login_user,
            permission_level,
            dept_subtree_ids=dept_subtree_ids,
            creator_user_id=creator_user_id,
        ):
            return

        if creator_user_id is not None and int(creator_user_id) != int(login_user.user_id):
            raise RolePermissionDeniedError(msg='Only the role creator can edit or delete this role')
        raise RolePermissionDeniedError()

    @classmethod
    async def _get_role_creator_ids(cls, roles) -> dict[int, int]:
        """Resolve role_id -> creator user ID from role table, then audit-log fallback."""
        role_ids = [int(r.id) for r in roles if getattr(r, 'id', None)]
        if not role_ids:
            return {}

        creator_ids = await cls._get_direct_role_creator_ids(role_ids)
        missing_role_ids = [rid for rid in role_ids if rid not in creator_ids]
        if not missing_role_ids:
            return creator_ids

        fallback_ids = await cls._get_audit_log_role_creator_ids(missing_role_ids)
        creator_ids.update(fallback_ids)
        return creator_ids

    @classmethod
    async def _get_direct_role_creator_ids(cls, role_ids: list[int]) -> dict[int, int]:
        """Read creator IDs from ``role.create_user`` for the given role IDs."""
        if not role_ids:
            return {}
        try:
            from sqlalchemy import text

            placeholders = ', '.join([f':rid_{i}' for i in range(len(role_ids))])
            params = {f'rid_{i}': rid for i, rid in enumerate(role_ids)}
            sql = text(f'SELECT id, create_user FROM role WHERE id IN ({placeholders})')

            async with get_async_db_session() as session:
                rows = (await session.execute(sql, params)).all()
        except Exception as e:
            logger.debug('Skip role creator query: %s', e)
            return {}

        role_to_uid: dict[int, int] = {}
        for row in rows:
            rid = row[0]
            uid = row[1]
            if uid:
                role_to_uid[int(rid)] = int(uid)
        return role_to_uid

    @classmethod
    async def _get_audit_log_role_creator_ids(cls, role_ids: list[int]) -> dict[int, int]:
        """Fallback: infer creators from the earliest ``create_role`` audit log per role."""
        if not role_ids:
            return {}
        try:
            from sqlalchemy import text

            placeholders = ', '.join([f':rid_{i}' for i in range(len(role_ids))])
            params = {
                'system_id': 'system',
                'event_type': 'create_role',
                'object_type': 'role_conf',
            }
            params.update({f'rid_{i}': str(rid) for i, rid in enumerate(role_ids)})
            sql = text(
                'SELECT t.object_id, t.operator_id '
                'FROM ('
                '  SELECT object_id, operator_id, '
                '         ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY create_time ASC, id ASC) AS rn '
                '  FROM auditlog '
                '  WHERE system_id = :system_id '
                '    AND event_type = :event_type '
                '    AND object_type = :object_type '
                f'    AND object_id IN ({placeholders})'
                ') t '
                'WHERE t.rn = 1'
            )

            async with get_async_db_session() as session:
                rows = (await session.execute(sql, params)).all()
        except Exception as e:
            logger.debug('Skip role creator audit-log fallback query: %s', e)
            return {}

        role_to_uid: dict[int, int] = {}
        for row in rows:
            role_id = row[0]
            user_id = row[1]
            if role_id and user_id:
                try:
                    role_to_uid[int(role_id)] = int(user_id)
                except (TypeError, ValueError):
                    continue
        return role_to_uid

    @classmethod
    async def _get_creator_names(cls, creator_ids: dict[int, int]) -> dict[int, str]:
        """Resolve creator_name for roles from role.create_user -> user.user_name."""
        user_ids = sorted({uid for uid in creator_ids.values() if uid})
        if not user_ids:
            return {}

        users = await UserDao.aget_user_by_ids(user_ids) or []
        user_name_map = {u.user_id: u.user_name for u in users}
        return {
            rid: user_name_map.get(uid)
            for rid, uid in creator_ids.items()
            if user_name_map.get(uid)
        }

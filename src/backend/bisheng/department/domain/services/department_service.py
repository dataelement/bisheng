"""DepartmentService — core business logic for department tree management.

Part of F002-department-tree.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import List, Optional, Set

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from bisheng.common.errcode.department import (
    DepartmentCircularMoveError,
    DepartmentHasChildrenError,
    DepartmentHasMembersError,
    DepartmentInvalidPasswordError,
    DepartmentInvalidRolesError,
    DepartmentMemberDeleteBlockedError,
    DepartmentMemberDeleteForbiddenError,
    DepartmentMemberExistsError,
    DepartmentMemberNotFoundError,
    DepartmentNameDuplicateError,
    DepartmentNotArchivedError,
    DepartmentArchivedReadonlyError,
    DepartmentParentArchivedError,
    DepartmentNotFoundError,
    DepartmentPersonIdDeletedAccountError,
    DepartmentPersonIdDuplicateError,
    DepartmentPersonIdRequiredError,
    DepartmentPermissionDeniedError,
    DepartmentRootExistsError,
    DepartmentSourceReadonlyError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import (
    Department,
    DepartmentDao,
    UserDepartment,
    UserDepartmentDao,
)
from bisheng.database.models.department_admin_grant import (
    DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
    DepartmentAdminGrantDao,
)
from bisheng.department.domain.schemas.department_schema import (
    DepartmentCreate,
    DepartmentLocalMemberCreate,
    DepartmentMemberAdd,
    DepartmentMemberEditApply,
    DepartmentMoveRequest,
    DepartmentTreeNode,
    DepartmentUpdate,
)
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService

logger = logging.getLogger(__name__)

# AdminRole = 1, same as bisheng.database.constants.AdminRole
_ADMIN_ROLE_ID = 1


async def _aget_fga_client_with_fallback():
    """Return the async FGA client, with sync fallback for degraded contexts."""
    from bisheng.core.openfga.manager import aget_fga_client, get_fga_client

    fga = await aget_fga_client()
    if fga is not None:
        return fga
    return get_fga_client()


def _is_admin(login_user) -> bool:
    """Temporary admin check — F004 will replace with PermissionService.check().

    Checks if AdminRole (id=1) is in login_user.user_role.
    """
    if hasattr(login_user, 'user_role') and isinstance(login_user.user_role, list):
        return _ADMIN_ROLE_ID in login_user.user_role
    return False


async def _check_permission(
    login_user, dept_internal_id: Optional[int] = None,
) -> None:
    """Two-tier permission check: system admin OR department admin via OpenFGA.

    Args:
        login_user: Current user payload.
        dept_internal_id: Database ID of the target department. When provided,
            checks if the user is an admin of that department (or any ancestor
            via OpenFGA's parent-admin inheritance).

    When OpenFGA is missing ``department:parent#parent department:child`` tuples,
    inherited ``admin`` checks on the child can fail while MySQL ``path`` still
    places the node under an admin's subtree (left tree vs member API mismatch).
    In that case we walk ``parent_id`` in DB and re-use ``PermissionService.check``
    on each ancestor — same outcome as a fully synced FGA graph without widening
    scope beyond the org tree.
    """
    # L1: System admin → pass
    if _is_admin(login_user):
        return
    # L2: Department admin → check via OpenFGA
    if dept_internal_id is not None:
        try:
            from bisheng.permission.domain.services.permission_service import (
                PermissionService,
            )
            is_dept_admin = await PermissionService.check(
                user_id=login_user.user_id,
                relation='admin',
                object_type='department',
                object_id=str(dept_internal_id),
                login_user=login_user,
            )
            if is_dept_admin:
                return
            # L2b: DB parent chain — tolerate missing FGA ``parent`` edges on some nodes
            seen: Set[int] = {int(dept_internal_id)}
            row = await DepartmentDao.aget_by_id(int(dept_internal_id))
            while row is not None and row.parent_id is not None:
                pid = int(row.parent_id)
                if pid in seen:
                    break
                seen.add(pid)
                if await PermissionService.check(
                    user_id=login_user.user_id,
                    relation='admin',
                    object_type='department',
                    object_id=str(pid),
                    login_user=login_user,
                ):
                    return
                row = await DepartmentDao.aget_by_id(pid)
        except Exception:
            logger.warning(
                'PermissionService.check failed for dept admin, user=%d dept=%d',
                login_user.user_id, dept_internal_id,
            )
    raise DepartmentPermissionDeniedError()


async def _is_tenant_admin(login_user) -> bool:
    """Check whether the current user has tenant-admin rights."""
    tenant_id = getattr(login_user, 'tenant_id', None)
    if tenant_id is None:
        return False
    try:
        from bisheng.permission.domain.services.permission_service import (
            PermissionService,
        )
        return await PermissionService.check(
            user_id=login_user.user_id,
            relation='admin',
            object_type='tenant',
            object_id=str(tenant_id),
            login_user=login_user,
        )
    except Exception as e:
        logger.warning(
            'PermissionService.check failed for tenant admin, user=%s tenant=%s: %s',
            getattr(login_user, 'user_id', None),
            tenant_id,
            e,
        )
        return False


def _get_dept_id_prefix() -> str:
    from bisheng.common.services.config_service import settings
    prefix = settings.get_from_db('dept_id_prefix')
    return prefix if isinstance(prefix, str) and prefix else 'BS'


def _is_registration_enabled() -> bool:
    """Whether self-registration is enabled in system config."""
    from bisheng.common.services.config_service import settings

    env_conf = settings.get_from_db('env') or {}
    if not isinstance(env_conf, dict):
        return True

    raw = env_conf.get('enable_registration', True)
    if isinstance(raw, str):
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(raw)


def generate_dept_id(prefix: str = 'BS') -> str:
    """Generate a business key like 'BS@a3f7e9'."""
    return f'{prefix}@{secrets.token_hex(3)}'


def _password_meets_prd_policy(plain: str) -> bool:
    """PRD：至少 8 位，含大写、小写、数字、符号。"""
    if len(plain) < 8:
        return False
    return bool(
        re.search(r'[A-Z]', plain)
        and re.search(r'[a-z]', plain)
        and re.search(r'\d', plain)
        and re.search(r'[^A-Za-z0-9\s]', plain),
    )


async def _get_dept_or_raise(session, dept_id: str) -> Department:
    """Look up department by business key, raise DepartmentNotFoundError if missing."""
    result = await session.exec(
        select(Department).where(Department.dept_id == dept_id)
    )
    dept = result.first()
    if not dept:
        raise DepartmentNotFoundError()
    return dept


async def _get_dept_and_check_permission(session, dept_id: str, login_user) -> Department:
    """Look up department + permission check without leaking resource existence.

    Non-admin users get DepartmentPermissionDeniedError for both
    'not found' and 'no access' to prevent enumeration.
    """
    result = await session.exec(
        select(Department).where(Department.dept_id == dept_id)
    )
    dept = result.first()
    if not dept:
        if _is_admin(login_user):
            raise DepartmentNotFoundError()
        raise DepartmentPermissionDeniedError()
    await _check_permission(login_user, dept_internal_id=dept.id)
    return dept


async def _ensure_department_can_archive(session, dept: Department) -> None:
    """Validate archive preconditions before mutating department state."""
    children = (await session.exec(
        select(Department).where(
            Department.parent_id == dept.id,
            Department.status == 'active',
        )
    )).first()
    if children:
        raise DepartmentHasChildrenError()

    count_result = await session.exec(
        select(func.count(UserDepartment.id)).where(
            UserDepartment.department_id == dept.id,
        )
    )
    if count_result.one() > 0:
        raise DepartmentHasMembersError()


async def _ensure_department_can_purge(session, dept: Department) -> None:
    """Validate permanent-delete preconditions before deleting related rows."""
    child = (await session.exec(
        select(Department.id).where(
            Department.parent_id == dept.id,
        )
    )).first()
    if child is not None:
        raise DepartmentHasChildrenError()

    count_result = await session.exec(
        select(func.count(UserDepartment.id)).where(
            UserDepartment.department_id == dept.id,
        )
    )
    if count_result.one() > 0:
        raise DepartmentHasMembersError()


class DepartmentService:

    @classmethod
    async def acreate_department(
        cls, data: DepartmentCreate, login_user,
    ) -> Department:
        await _check_permission(login_user, dept_internal_id=data.parent_id)

        async with get_async_db_session() as session:
            # Validate parent exists and is active
            parent = (await session.exec(
                select(Department).where(Department.id == data.parent_id)
            )).first()
            if not parent or parent.status != 'active':
                raise DepartmentNotFoundError(msg='Parent department not found')

            # Check name duplicate at same level
            dup = (await session.exec(
                select(Department).where(
                    Department.parent_id == data.parent_id,
                    Department.name == data.name,
                    Department.status == 'active',
                )
            )).first()
            if dup:
                raise DepartmentNameDuplicateError()

            # Generate dept_id with retry (3 attempts + 1 fallback with longer hex)
            dept_id = None
            for _ in range(3):
                candidate = generate_dept_id(_get_dept_id_prefix())
                existing = (await session.exec(
                    select(Department).where(Department.dept_id == candidate)
                )).first()
                if not existing:
                    dept_id = candidate
                    break
            if dept_id is None:
                # Fallback: longer hex to minimize collision
                dept_id = f'BS@{secrets.token_hex(6)}'

            # INSERT department
            dept = Department(
                dept_id=dept_id,
                name=data.name,
                parent_id=data.parent_id,
                sort_order=data.sort_order,
                default_role_ids=data.default_role_ids,
                source='local',
                external_id=dept_id,
                status='active',
                create_user=login_user.user_id,
            )
            session.add(dept)
            await session.flush()
            await session.refresh(dept)

            # UPDATE path (two-phase: need auto_increment id first)
            dept.path = f'{parent.path}{dept.id}/'
            session.add(dept)
            await session.commit()
            await session.refresh(dept)

        # Fire change handler (outside session)
        ops = DepartmentChangeHandler.on_created(dept.id, parent.id)
        await DepartmentChangeHandler.execute_async(ops)

        # Set initial admins if provided
        if data.admin_user_ids:
            ops = DepartmentChangeHandler.on_admin_set(dept.id, data.admin_user_ids)
            await DepartmentChangeHandler.execute_async(ops)
            for uid in data.admin_user_ids:
                await DepartmentAdminGrantDao.aupsert(
                    int(uid), int(dept.id), DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
                )

        return dept

    @classmethod
    async def aget_tree(cls, login_user) -> List[DepartmentTreeNode]:
        # System admin and tenant admin see full tree; dept admin sees subtree only.
        is_sys_admin = _is_admin(login_user)
        is_tenant_admin = False
        admin_depts = []
        if not is_sys_admin:
            admin_depts = await DepartmentDao.aget_user_admin_departments(
                login_user.user_id,
            )
            if not admin_depts:
                is_tenant_admin = await _is_tenant_admin(login_user)
            if not admin_depts and not is_tenant_admin:
                raise DepartmentPermissionDeniedError()

        async with get_async_db_session() as session:
            # Get all departments (including archived) for current tenant
            result = await session.exec(
                select(Department).where(
                    Department.status.in_(['active', 'archived'])
                )
            )
            depts = result.all()

            if not depts:
                return []

            # "临时访客" 仅在开放注册时展示
            if not _is_registration_enabled():
                depts = [d for d in depts if d.dept_id != 'BS@guest']
                if not depts:
                    return []

            # Filter to dept admin's subtree if not system admin
            if not is_sys_admin and not is_tenant_admin:
                admin_paths = {d.path for d in admin_depts}
                depts = [
                    d for d in depts
                    if any(d.path.startswith(p) for p in admin_paths)
                ]
                if not depts:
                    return []

            # Batch get member counts
            dept_ids = [d.id for d in depts]
            count_result = await session.exec(
                select(
                    UserDepartment.department_id,
                    func.count(UserDepartment.id),
                )
                .where(UserDepartment.department_id.in_(dept_ids))
                .group_by(UserDepartment.department_id)
            )
            count_map = dict(count_result.all())

        # Build tree in memory
        nodes = {}
        for d in depts:
            nodes[d.id] = DepartmentTreeNode(
                id=d.id,
                dept_id=d.dept_id,
                name=d.name,
                parent_id=d.parent_id,
                path=d.path,
                sort_order=d.sort_order,
                source=d.source,
                status=d.status,
                member_count=count_map.get(d.id, 0),
                children=[],
            )

        roots = []
        for node in nodes.values():
            if node.parent_id is not None and node.parent_id in nodes:
                nodes[node.parent_id].children.append(node)
            else:
                roots.append(node)

        # Sort children by sort_order
        def _sort(node_list: List[DepartmentTreeNode]):
            node_list.sort(key=lambda n: n.sort_order)
            for n in node_list:
                _sort(n.children)

        _sort(roots)
        return roots

    @classmethod
    async def aget_department(cls, dept_id: str, login_user) -> dict:
        async with get_async_db_session() as session:
            dept = await _get_dept_or_raise(session, dept_id)

            count_result = await session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == dept.id,
                )
            )
            member_count = count_result.one()

        await _check_permission(login_user, dept_internal_id=dept.id)

        data = dept.model_dump()
        data['member_count'] = member_count
        return data

    @classmethod
    async def aupdate_department(
        cls, dept_id: str, data: DepartmentUpdate, login_user,
    ) -> Department:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            if dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()

            # Source-readonly check
            if dept.source != 'local' and data.name is not None:
                raise DepartmentSourceReadonlyError()

            # Name duplicate check
            if data.name is not None:
                dup = (await session.exec(
                    select(Department).where(
                        Department.parent_id == dept.parent_id,
                        Department.name == data.name,
                        Department.status == 'active',
                        Department.id != dept.id,
                    )
                )).first()
                if dup:
                    raise DepartmentNameDuplicateError()

            # Apply updates (only non-None fields)
            if data.name is not None:
                dept.name = data.name
            if data.sort_order is not None:
                dept.sort_order = data.sort_order
            if data.default_role_ids is not None:
                dept.default_role_ids = data.default_role_ids

            session.add(dept)
            await session.commit()
            await session.refresh(dept)

        if data.admin_user_ids is not None:
            await cls.aset_admins(dept_id, list(data.admin_user_ids), login_user)

        return dept

    @classmethod
    async def adelete_department(cls, dept_id: str, login_user) -> None:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.dept_id == 'BS@guest':
                raise DepartmentPermissionDeniedError(msg='Guest department cannot be deleted')

            await _ensure_department_can_archive(session, dept)

            parent_id = dept.parent_id
            dept.status = 'archived'
            session.add(dept)
            await session.commit()

        # Fire change handler
        if parent_id is not None:
            ops = DepartmentChangeHandler.on_archived(dept.id, parent_id)
            await DepartmentChangeHandler.execute_async(ops)

        # Notify Gateway to clean up traffic control rules
        import json
        from bisheng.core.cache.redis_manager import get_redis_client_sync
        try:
            redis_client = get_redis_client_sync()
            msg = json.dumps({'id': dept.id})
            redis_client.rpush('delete_department', msg, expiration=86400)
            redis_client.publish('delete_department', msg)
        except Exception:
            logger.warning('Failed to publish delete_department event for dept %s', dept.id)

    @classmethod
    async def apurge_department(cls, dept_id: str, login_user) -> None:
        """Permanently delete an archived department and clean up all references."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.dept_id == 'BS@guest':
                raise DepartmentPermissionDeniedError(msg='Guest department cannot be deleted')

            if dept.status != 'archived':
                raise DepartmentNotArchivedError()

            await _ensure_department_can_purge(session, dept)

            dept_internal_id = dept.id

            member_user_ids: list[int] = []

            # Delete department-scoped roles and their user_role bindings
            from bisheng.database.models.role import Role
            from bisheng.user.domain.models.user_role import UserRole
            scoped_role_ids = (await session.exec(
                select(Role.id).where(Role.department_id == dept_internal_id)
            )).all()
            if scoped_role_ids:
                await session.exec(
                    delete(UserRole).where(UserRole.role_id.in_(scoped_role_ids))
                )
                await session.exec(
                    delete(Role).where(Role.department_id == dept_internal_id)
                )

            # Physical delete
            await session.delete(dept)
            await session.commit()

        # Collect admin user_ids from OpenFGA
        admin_user_ids: list[int] = []
        from bisheng.core.openfga.manager import aget_fga_client
        fga = await aget_fga_client()
        if fga is not None:
            try:
                tuples = await fga.read_tuples(
                    relation='admin', object=f'department:{dept_internal_id}',
                )
                for t in tuples:
                    user_str = t.get('user', '') if isinstance(t, dict) else ''
                    if not user_str and isinstance(t.get('key'), dict):
                        user_str = t['key'].get('user', '')
                    if user_str.startswith('user:'):
                        try:
                            admin_user_ids.append(int(user_str.split(':', 1)[1]))
                        except ValueError:
                            continue
            except Exception:
                logger.warning('FGA read_tuples failed during purge of department %s', dept_id)

        # Clean up OpenFGA tuples
        ops = DepartmentChangeHandler.on_purged(dept_internal_id, member_user_ids, admin_user_ids)
        await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def arestore_department(cls, dept_id: str, login_user) -> None:
        """Restore an archived department to active status."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.status != 'archived':
                raise DepartmentNotArchivedError(msg='Only archived departments can be restored')

            if dept.parent_id is not None:
                parent = await DepartmentDao.aget_by_id(dept.parent_id)
                if parent and parent.status == 'archived':
                    raise DepartmentParentArchivedError()

            dept.status = 'active'
            session.add(dept)
            await session.commit()

    @classmethod
    async def amove_department(
        cls, dept_id: str, data: DepartmentMoveRequest, login_user,
    ) -> Department:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            # Load new parent
            new_parent = (await session.exec(
                select(Department).where(Department.id == data.new_parent_id)
            )).first()
            if not new_parent or new_parent.status != 'active':
                raise DepartmentNotFoundError(msg='New parent department not found')

            # Circular detection: can't move to self
            if data.new_parent_id == dept.id:
                raise DepartmentCircularMoveError()

            # Circular detection: can't move to own subtree
            if new_parent.path.startswith(dept.path):
                raise DepartmentCircularMoveError()

            old_parent_id = dept.parent_id
            old_path = dept.path
            new_path = f'{new_parent.path}{dept.id}/'

            # Batch update subtree paths
            await session.execute(
                update(Department)
                .where(Department.path.like(f'{old_path}%'))
                .values(path=func.replace(Department.path, old_path, new_path))
            )

            # Update department itself
            dept.parent_id = data.new_parent_id
            dept.path = new_path
            session.add(dept)
            await session.commit()
            await session.refresh(dept)

        # Fire change handler
        ops = DepartmentChangeHandler.on_moved(dept.id, old_parent_id, data.new_parent_id)
        await DepartmentChangeHandler.execute_async(ops)

        return dept

    @classmethod
    async def acreate_root_department(
        cls, tenant_id: int, name: str = 'Default Organization',
    ) -> Department:
        """Create the root department for a tenant.

        Uses bypass_tenant_filter() since this operates on a specific tenant_id.
        Called by init_data (F002) and tenant creation flow (F010).
        """
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.tenant import Tenant

        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                # Check if root already exists
                existing = (await session.exec(
                    select(Department).where(
                        Department.parent_id.is_(None),
                        Department.tenant_id == tenant_id,
                        Department.status == 'active',
                    )
                )).first()
                if existing:
                    raise DepartmentRootExistsError()

                # Generate dept_id for root
                dept_id = generate_dept_id(_get_dept_id_prefix())

                dept = Department(
                    dept_id=dept_id,
                    name=name,
                    parent_id=None,
                    tenant_id=tenant_id,
                    path='',
                    source='local',
                    external_id=dept_id,
                    status='active',
                )
                session.add(dept)
                await session.flush()
                await session.refresh(dept)

                # Set path to /{id}/
                dept.path = f'/{dept.id}/'
                session.add(dept)

                # Update tenant.root_dept_id
                tenant = (await session.exec(
                    select(Tenant).where(Tenant.id == tenant_id)
                )).first()
                if tenant:
                    tenant.root_dept_id = dept.id
                    session.add(tenant)

                await session.commit()
                await session.refresh(dept)

        return dept

    @classmethod
    async def aadd_members(
        cls, dept_id: str, data: DepartmentMemberAdd, login_user,
    ) -> None:
        default_role_ids_snapshot: List[int] = []
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()
            raw_defaults = dept.default_role_ids or []
            default_role_ids_snapshot = [int(x) for x in raw_defaults if x is not None]

            # Batch check for existing members (single query instead of N)
            existing_result = await session.exec(
                select(UserDepartment.user_id).where(
                    UserDepartment.user_id.in_(data.user_ids),
                    UserDepartment.department_id == dept.id,
                )
            )
            existing_ids = existing_result.all()
            if existing_ids:
                raise DepartmentMemberExistsError(
                    msg=f'Users {existing_ids} are already members of this department',
                )

            # Batch insert
            for uid in data.user_ids:
                session.add(UserDepartment(
                    user_id=uid,
                    department_id=dept.id,
                    is_primary=data.is_primary,
                    source='local',
                ))
            await session.commit()

        # Fire change handler
        ops = DepartmentChangeHandler.on_members_added(dept.id, data.user_ids)
        await DepartmentChangeHandler.execute_async(ops)

        # 部门「默认角色」：加入本部门后自动授予（可分配域内、且用户尚未拥有）
        if default_role_ids_snapshot:
            from bisheng.database.constants import AdminRole
            from bisheng.user.domain.models.user_role import UserRoleDao

            assignable = await cls.aget_assignable_roles(dept_id, login_user)
            allowed_ids = {r['id'] for r in assignable}
            to_apply = [
                rid for rid in default_role_ids_snapshot
                if rid != AdminRole and rid in allowed_ids
            ]
            if to_apply:
                for uid in data.user_ids:
                    existing = {int(ur.role_id) for ur in UserRoleDao.get_user_roles(uid)}
                    need_add = [r for r in to_apply if r not in existing]
                    if need_add:
                        UserRoleDao.add_user_roles(uid, need_add)
                        await LegacyRBACSyncService.sync_user_role_change(
                            uid,
                            existing,
                            existing | set(need_add),
                        )

    @classmethod
    async def aremove_member(
        cls, dept_id: str, user_id: int, login_user,
    ) -> None:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()

            # Check member exists
            ud = (await session.exec(
                select(UserDepartment).where(
                    UserDepartment.user_id == user_id,
                    UserDepartment.department_id == dept.id,
                )
            )).first()
            if not ud:
                raise DepartmentMemberNotFoundError()

            await session.delete(ud)
            await session.commit()

        # Fire change handler：移除成员同时卸掉该部门的部门管理员（FGA）
        ops = (
            DepartmentChangeHandler.on_member_removed(dept.id, user_id)
            + DepartmentChangeHandler.on_admin_removed(dept.id, [user_id])
        )
        await DepartmentChangeHandler.execute_async(ops)
        await DepartmentAdminGrantDao.adelete(user_id, int(dept.id))
        from bisheng.knowledge.domain.services.department_knowledge_space_service import (
            DepartmentKnowledgeSpaceService,
        )
        await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
            request=None,
            login_user=login_user,
            department_id=dept.id,
            added_user_ids=[],
            removed_user_ids=[user_id],
        )

    @classmethod
    async def _aget_department_admin_user_ids(cls, dept_internal_id: int) -> Set[int]:
        """OpenFGA：在 department:{id} 上具有 admin 关系的用户 ID 集合。"""
        fga = await _aget_fga_client_with_fallback()
        if fga is None:
            return set(await DepartmentAdminGrantDao.aget_user_ids_by_department(
                int(dept_internal_id),
            ))
        try:
            tuples = await fga.read_tuples(
                relation='admin', object=f'department:{dept_internal_id}',
            )
        except Exception:
            logger.warning(
                'FGA read_tuples failed for department admin ids dept=%s', dept_internal_id,
            )
            return set(await DepartmentAdminGrantDao.aget_user_ids_by_department(
                int(dept_internal_id),
            ))
        user_ids: Set[int] = set()
        for t in tuples:
            user_str = t.get('user', '') if isinstance(t, dict) else ''
            if not user_str and isinstance(t.get('key'), dict):
                user_str = t['key'].get('user', '')
            if user_str.startswith('user:'):
                try:
                    user_ids.add(int(user_str.split(':', 1)[1]))
                except ValueError:
                    continue
        return user_ids

    @classmethod
    async def aget_admins(
        cls, dept_id: str, login_user,
    ) -> List[dict]:
        """Get admin users of a department from OpenFGA."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

        user_ids = list(await cls._aget_department_admin_user_ids(dept.id))
        if not user_ids:
            return []

        from bisheng.user.domain.models.user import User
        async with get_async_db_session() as session:
            result = await session.exec(
                select(User.user_id, User.user_name).where(
                    User.user_id.in_(user_ids), User.delete == 0,
                )
            )
            return [{'user_id': r[0], 'user_name': r[1]} for r in result.all()]

    @classmethod
    async def aset_admins(
        cls, dept_id: str, user_ids: List[int], login_user,
    ) -> List[dict]:
        """Set department admins (full replace). Returns updated admin list."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            if dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()

        # Get current admins from FGA
        current_admins = await cls.aget_admins(dept_id, login_user)
        current_ids = {a['user_id'] for a in current_admins}
        new_ids = set(user_ids)

        to_add = list(new_ids - current_ids)
        to_remove = list(current_ids - new_ids)

        if to_add:
            ops = DepartmentChangeHandler.on_admin_set(dept.id, to_add)
            await DepartmentChangeHandler.execute_async(ops)
            for uid in to_add:
                await DepartmentAdminGrantDao.aupsert(
                    int(uid), int(dept.id), DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
                )
        if to_remove:
            ops = DepartmentChangeHandler.on_admin_removed(dept.id, to_remove)
            await DepartmentChangeHandler.execute_async(ops)
            await DepartmentAdminGrantDao.adelete_for_department_users(
                int(dept.id), [int(u) for u in to_remove],
            )

        if to_add or to_remove:
            from bisheng.knowledge.domain.services.department_knowledge_space_service import (
                DepartmentKnowledgeSpaceService,
            )
            await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
                request=None,
                login_user=login_user,
                department_id=dept.id,
                added_user_ids=to_add,
                removed_user_ids=to_remove,
            )

        return await cls.aget_admins(dept_id, login_user)

    @classmethod
    async def aget_members(
        cls, dept_id: str, page: int, limit: int,
        keyword: str, login_user,
        is_primary: Optional[int] = None,
    ) -> dict:

        # Cap pagination params
        page = max(1, page)
        limit = max(1, min(limit, 100))

        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            from bisheng.user.domain.models.user import User

            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    User.external_id.label('user_external_id'),
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time.label('member_join_time'),
                    User.create_time.label('user_create_time'),
                    User.update_time.label('user_update_time'),
                    User.delete.label('user_deleted'),
                )
                .join(User, User.user_id == UserDepartment.user_id)
                .where(
                    UserDepartment.department_id == dept.id,
                )
            )
            if keyword:
                base = base.where(User.user_name.like(f'%{keyword}%'))
            if is_primary is not None:
                base = base.where(UserDepartment.is_primary == is_primary)

            total_result = await session.exec(
                select(func.count()).select_from(base.subquery())
            )
            total = total_result.one()

            rows_result = await session.exec(
                base.offset((page - 1) * limit).limit(limit)
            )
            rows = rows_result.all()

        # Batch enrich: user_groups and roles
        user_ids = [r.user_id for r in rows]
        user_groups_map: dict = {}
        roles_map: dict = {}

        if user_ids:
            async with get_async_db_session() as session:
                # User groups
                from bisheng.database.models.group import Group, LEGACY_HIDDEN_USER_GROUP_NAMES
                from bisheng.database.models.user_group import UserGroup
                ug_result = await session.exec(
                    select(
                        UserGroup.user_id,
                        Group.id,
                        Group.group_name,
                    )
                    .join(Group, UserGroup.group_id == Group.id)
                    .where(
                        UserGroup.user_id.in_(user_ids),
                        Group.visibility == 'public',
                        col(Group.group_name).notin_(LEGACY_HIDDEN_USER_GROUP_NAMES),
                    )
                )
                for uid, gid, gname in ug_result.all():
                    user_groups_map.setdefault(uid, []).append(
                        {'id': gid, 'group_name': gname},
                    )

                # Roles
                from bisheng.database.models.role import Role
                from bisheng.user.domain.models.user_role import UserRole
                role_result = await session.exec(
                    select(
                        UserRole.user_id,
                        Role.id,
                        Role.role_name,
                    )
                    .join(Role, UserRole.role_id == Role.id)
                    .where(UserRole.user_id.in_(user_ids))
                )
                for uid, rid, rname in role_result.all():
                    roles_map.setdefault(uid, []).append(
                        {'id': rid, 'role_name': rname},
                    )

        admin_uids = await cls._aget_department_admin_user_ids(dept.id)

        def _last_modified(row) -> object:
            """成员行「修改时间」：取加入部门、用户创建、用户最近更新中的最晚时刻。"""
            times = [
                row.member_join_time,
                row.user_create_time,
                row.user_update_time,
            ]
            valid = [x for x in times if x is not None]
            return max(valid) if valid else None

        def _person_id_for_row(row) -> Optional[str]:
            ext = getattr(row, 'user_external_id', None)
            if ext:
                return str(ext)
            return None

        data = [
            {
                'user_id': r.user_id,
                'user_name': r.user_name,
                'person_id': _person_id_for_row(r),
                'department_id': r.department_id,
                'is_primary': r.is_primary,
                'source': r.source,
                'create_time': r.member_join_time,
                'update_time': _last_modified(r),
                'enabled': r.user_deleted == 0,
                'user_groups': user_groups_map.get(r.user_id, []),
                'roles': roles_map.get(r.user_id, []),
                'is_department_admin': r.user_id in admin_uids,
            }
            for r in rows
        ]
        return {'data': data, 'total': total}

    @classmethod
    async def aget_global_members_search(
        cls, keyword: str, page: int, limit: int, login_user,
    ) -> dict:
        """Search members by username across visible org tree (primary department only).

        数据范围与左侧部门树一致：先取 :meth:`aget_tree` 的可见节点 id 集合，仅返回主属部门
        落在该集合内的用户（系统超管 / 租户管理员 / 部门管理员子树与树接口相同）。
        """
        kw = (keyword or '').strip()
        if not kw:
            return {'data': [], 'total': 0}
        page = max(1, page)
        limit = max(1, min(limit, 50))

        tree = await cls.aget_tree(login_user)

        def _collect_visible_ids(nodes: List[DepartmentTreeNode]) -> Set[int]:
            out: Set[int] = set()
            for n in nodes:
                out.add(int(n.id))
                if n.children:
                    out |= _collect_visible_ids(n.children)
            return out

        visible_ids = _collect_visible_ids(tree)
        if not visible_ids:
            return {'data': [], 'total': 0}

        async with get_async_db_session() as session:
            from bisheng.user.domain.models.user import User

            name_rows = await session.exec(
                select(Department.id, Department.name).where(
                    Department.status == 'active',
                )
            )
            id_to_name = {int(r.id): r.name for r in name_rows.all()}

            def _primary_dept_display_path(dept: Department) -> str:
                """path 列为祖先内部 id 链（如 ``/22/``），通常不含本部门 id；根常为 ``/``。

                展示「自根到主属部门」的名称链，避免只显示父级或根路径解析为空。
                """
                labels: List[str] = []
                ancestor_ids: List[int] = []
                for part in (dept.path or '').split('/'):
                    if not part.strip():
                        continue
                    try:
                        i = int(part)
                    except ValueError:
                        continue
                    ancestor_ids.append(i)
                    labels.append(id_to_name.get(i, f'#{i}'))
                self_id = int(dept.id)
                self_nm = id_to_name.get(self_id) or (dept.name or '')
                if self_id not in ancestor_ids and self_nm:
                    labels.append(self_nm)
                return '/'.join(labels) if labels else (self_nm or '')

            base_group = (
                select(
                    User.user_id,
                    User.user_name,
                    func.min(Department.id).label('dept_int_id'),
                )
                .join(
                    UserDepartment,
                    (UserDepartment.user_id == User.user_id)
                    & (UserDepartment.is_primary == 1),
                )
                .join(Department, Department.id == UserDepartment.department_id)
                .where(
                    User.delete == 0,
                    Department.status == 'active',
                    col(Department.id).in_(visible_ids),
                    User.user_name.like(f'%{kw}%'),
                )
                .group_by(User.user_id, User.user_name)
            )
            count_stmt = select(func.count()).select_from(base_group.subquery())
            total = (await session.exec(count_stmt)).one()

            page_stmt = (
                base_group.order_by(User.user_name)
                .offset((page - 1) * limit)
                .limit(limit)
            )
            rows = (await session.exec(page_stmt)).all()

            if not rows:
                return {'data': [], 'total': int(total)}

            dept_int_ids = [int(r.dept_int_id) for r in rows]
            dept_rows = (
                await session.exec(
                    select(Department).where(Department.id.in_(dept_int_ids))
                )
            ).all()
            dept_by_id = {int(d.id): d for d in dept_rows}

        data = []
        for r in rows:
            d = dept_by_id.get(int(r.dept_int_id))
            if not d:
                continue
            data.append(
                {
                    'user_id': int(r.user_id),
                    'user_name': r.user_name,
                    'primary_department_dept_id': d.dept_id,
                    'primary_department_path': _primary_dept_display_path(d),
                }
            )
        return {'data': data, 'total': int(total)}

    @staticmethod
    async def _aget_ancestor_chain_ids(session, dept: Department) -> List[int]:
        """沿 parent_id 自当前部门上至根，返回内部 id 列表（含当前与各级祖先）。

        用于角色可分配判定：作用域为部门 S 的角色，仅当「当前上下文部门 T 落在 S 的子树下」
        （即 S 为 T 的祖先或与 T 相同）时可授予；等价于 Role.department_id ∈ 本列表。
        """
        chain: List[int] = []
        seen: Set[int] = set()
        current: Optional[Department] = dept
        while current is not None and current.id is not None:
            cid = int(current.id)
            if cid in seen:
                break
            seen.add(cid)
            chain.append(cid)
            pid = current.parent_id
            if pid is None:
                break
            current = (
                await session.exec(select(Department).where(Department.id == int(pid)))
            ).first()
        return chain

    @classmethod
    async def aget_assignable_roles(
        cls, dept_id: str, login_user,
    ) -> List[dict]:
        """当前部门上下文中可授予的角色：全局 + 作用域落在上级链（含本部门）上的角色（不含内置超管）。

        规则：角色若绑定作用域部门 S，则可在任意「当前成员所属/操作上下文部门 T」为 S 或 S 的下级时使用；
        实现为 Role.department_id 为空，或 Role.department_id 属于当前部门 T 的祖先链（含 T）。
        """
        from bisheng.database.constants import AdminRole
        from bisheng.database.models.role import Role
        from bisheng.core.context.tenant import bypass_tenant_filter

        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            scope_chain_ids = await cls._aget_ancestor_chain_ids(session, dept)
            if not scope_chain_ids:
                scope_chain_ids = [int(dept.id)] if dept.id is not None else []

            # 作用域：department_id 为空表示无部门限制、全局可选；
            # 否则仅当角色作用域部门为「当前上下文部门的祖先或自身」时可授予（非兄弟子树）。
            dept_scope = or_(
                Role.department_id.is_(None),
                Role.department_id.in_(scope_chain_ids),
            )
            # Global built-in roles live outside child tenant scopes. The role
            # list API already bypasses the tenant filter and then explicitly
            # scopes tenant roles; keep this catalog aligned with it while
            # leaving department lookup/permission checks under normal scoping.
            with bypass_tenant_filter():
                stmt = select(Role).where(
                    Role.id > AdminRole,
                    or_(
                        and_(Role.role_type == 'global', dept_scope),
                        and_(
                            Role.role_type == 'tenant',
                            Role.tenant_id == login_user.tenant_id,
                            dept_scope,
                        ),
                        # 兼容旧数据：历史角色可能未写 role_type，默认按 tenant 角色处理
                        and_(
                            or_(Role.role_type.is_(None), Role.role_type == ''),
                            Role.tenant_id == login_user.tenant_id,
                            dept_scope,
                        ),
                    ),
                ).order_by(Role.role_name.asc())
                roles = (await session.exec(stmt)).all()

        return [
            {
                'id': r.id,
                'role_name': r.role_name,
                'role_type': r.role_type,
                'department_id': r.department_id,
            }
            for r in roles
        ]

    @classmethod
    async def acreate_local_member(
        cls, dept_id: str, data: DepartmentLocalMemberCreate, login_user,
    ) -> dict:
        """在部门内创建本地账号：主属当前部门、指定角色、生成人员 ID（external_id）；用户组非必填。"""
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import User, UserDao
        from bisheng.user.domain.services.user import UserService
        from bisheng.utils import md5_hash

        default_role_ids_snapshot: List[int] = []
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()
            raw_defaults = dept.default_role_ids or []
            default_role_ids_snapshot = [int(x) for x in raw_defaults if x is not None]

        plain = UserService.decrypt_password_plain(data.password)
        if not _password_meets_prd_policy(plain):
            raise DepartmentInvalidPasswordError()

        person_id = (data.person_id or '').strip()
        if not person_id:
            raise DepartmentPersonIdRequiredError()
        if await UserDao.aget_login_candidates_by_account(person_id):
            raise DepartmentPersonIdDuplicateError()
        if await UserDao.aexists_disabled_login_account(person_id):
            raise DepartmentPersonIdDeletedAccountError()

        assignable = await cls.aget_assignable_roles(dept_id, login_user)
        allowed_ids = {r['id'] for r in assignable}
        explicit_ids = [int(x) for x in (data.role_ids or [])]
        default_filtered = [
            rid for rid in default_role_ids_snapshot
            if rid != AdminRole and rid in allowed_ids
        ]
        final_role_ids = list(dict.fromkeys(explicit_ids + default_filtered))
        if AdminRole in final_role_ids or not set(final_role_ids).issubset(allowed_ids):
            raise DepartmentInvalidRolesError()

        pwd_hash = md5_hash(plain)
        user = User(
            user_name=data.user_name,
            password=pwd_hash,
            source='local',
            external_id=person_id,
        )
        try:
            user = UserDao.add_user_with_groups_and_roles(
                user, [], final_role_ids,
            )
        except IntegrityError:
            raise DepartmentPersonIdDuplicateError() from None
        await LegacyRBACSyncService.sync_user_auth_created(
            user.user_id,
            final_role_ids,
        )

        async with get_async_db_session() as session:
            dept = await _get_dept_or_raise(session, dept_id)
            ud = UserDepartment(
                user_id=user.user_id,
                department_id=dept.id,
                is_primary=1,
                source='local',
            )
            session.add(ud)
            await session.commit()

        ops = DepartmentChangeHandler.on_members_added(dept.id, [user.user_id])
        await DepartmentChangeHandler.execute_async(ops)

        return {
            'user_id': user.user_id,
            'user_name': user.user_name,
            'person_id': person_id,
            'dept_id': dept.dept_id,
        }

    @classmethod
    def _person_display_id(cls, user) -> str:
        """PRD 人员 ID：本地为 external_id（BS@…）；同步侧优先 external_id。"""
        if getattr(user, 'external_id', None):
            return str(user.external_id)
        return str(getattr(user, 'dept_id', None) or '')

    @classmethod
    async def _manageable_group_options(cls, login_user) -> List[dict]:
        """Return groups the current user can actually mutate."""
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        res = await UserGroupService.alist_manageable_groups(login_user)
        out = []
        for x in res or []:
            out.append({
                'id': x['id'],
                'group_name': x.get('group_name', ''),
                'visibility': x.get('visibility', 'public'),
            })
        return out

    @classmethod
    async def _assignable_role_id_set(cls, dept_key: str, login_user) -> set:
        rows = await cls.aget_assignable_roles(dept_key, login_user)
        return {int(r['id']) for r in rows}

    @classmethod
    async def _department_in_admin_writable_scope(
        cls, login_user, dept: Department,
    ) -> bool:
        """主部门可选范围：超管任意 active 部门；部门管理员为 FGA 管辖子树内部门。"""
        if not dept or getattr(dept, 'status', '') != 'active':
            return False
        if _is_admin(login_user):
            return True
        admin_depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
        if not admin_depts:
            return False
        paths = [d.path for d in admin_depts if getattr(d, 'path', None)]
        dp = dept.path or ''
        return any(dp.startswith(p) for p in paths)

    @classmethod
    async def _apply_local_primary_department_change(
        cls, user_id: int, new_dept_id: int,
    ) -> None:
        """将本地用户主部门切到 new_dept_id：从原主部门移除，不再保留为附属。"""
        old_dept_id_for_fga: Optional[int] = None
        fga_add_new: bool = False
        async with get_async_db_session() as session:
            uds = list(
                (await session.exec(
                    select(UserDepartment).where(UserDepartment.user_id == user_id),
                )).all()
            )
            primary_rows = [u for u in uds if int(u.is_primary or 0) == 1]
            old_primary = primary_rows[0] if primary_rows else None

            if not old_primary:
                target_ud = next(
                    (u for u in uds if int(u.department_id) == int(new_dept_id)),
                    None,
                )
                if target_ud:
                    target_ud.is_primary = 1
                    session.add(target_ud)
                else:
                    session.add(UserDepartment(
                        user_id=user_id,
                        department_id=new_dept_id,
                        is_primary=1,
                        source='local',
                    ))
                    fga_add_new = True
                await session.commit()
                if fga_add_new:
                    ops = DepartmentChangeHandler.on_members_added(new_dept_id, [user_id])
                    await DepartmentChangeHandler.execute_async(ops)
                return

            if int(old_primary.department_id) == int(new_dept_id):
                return

            old_dept_id_for_fga = int(old_primary.department_id)
            target_ud = next(
                (u for u in uds if int(u.department_id) == int(new_dept_id)),
                None,
            )

            await session.delete(old_primary)

            if target_ud:
                target_ud.is_primary = 1
                session.add(target_ud)
            else:
                session.add(UserDepartment(
                    user_id=user_id,
                    department_id=new_dept_id,
                    is_primary=1,
                    source='local',
                ))
                fga_add_new = True

            await session.commit()

        if old_dept_id_for_fga is not None:
            # 离开原部门后不再担任该部门的部门管理员（仅 FGA admin 关系）
            ops_rm = (
                DepartmentChangeHandler.on_member_removed(old_dept_id_for_fga, user_id)
                + DepartmentChangeHandler.on_admin_removed(old_dept_id_for_fga, [user_id])
            )
            await DepartmentChangeHandler.execute_async(ops_rm)
            await DepartmentAdminGrantDao.adelete(user_id, int(old_dept_id_for_fga))
        if fga_add_new:
            ops_add = DepartmentChangeHandler.on_members_added(new_dept_id, [user_id])
            await DepartmentChangeHandler.execute_async(ops_add)

    @classmethod
    async def _count_user_owned_data_assets(cls, user_id: int) -> dict:
        """删除人员前：统计用户作为创建者挂载的常见数据资产。"""
        from bisheng.database.models.assistant import Assistant
        from bisheng.database.models.flow import Flow
        from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum

        async with get_async_db_session() as session:
            k = await session.scalar(
                select(func.count(Knowledge.id)).where(
                    Knowledge.user_id == user_id,
                    Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                ),
            )
            f = await session.scalar(
                select(func.count(Flow.id)).where(Flow.user_id == user_id),
            )
            a = await session.scalar(
                select(func.count(Assistant.id)).where(
                    Assistant.user_id == user_id,
                    Assistant.is_delete == 0,
                ),
            )
        return {
            'knowledge_spaces': int(k or 0),
            'flows': int(f or 0),
            'assistants': int(a or 0),
        }

    @classmethod
    async def acheck_local_member_delete(
        cls, dept_id: str, user_id: int, login_user,
    ) -> dict:
        """删除人员前预检：是否挂载数据资产。"""
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import UserDao
        from bisheng.user.domain.models.user_role import UserRoleDao

        async with get_async_db_session() as session:
            ctx_dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if ctx_dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()
            mem = (
                await session.exec(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == ctx_dept.id,
                    ),
                )
            ).first()
        if not mem:
            raise DepartmentMemberNotFoundError()

        user = await UserDao.aget_user(user_id)
        if not user or user.delete != 0:
            raise DepartmentMemberNotFoundError()
        if getattr(user, 'source', 'local') != 'local':
            raise DepartmentMemberDeleteForbiddenError()

        old_roles = UserRoleDao.get_user_roles(user_id)
        if any(int(r.role_id) == AdminRole for r in old_roles):
            raise DepartmentPermissionDeniedError()

        counts = await cls._count_user_owned_data_assets(user_id)
        total = sum(counts.values())
        return {'has_assets': total > 0, 'counts': counts}

    @classmethod
    async def adelete_local_organization_member(
        cls, dept_id: str, user_id: int, login_user,
    ) -> None:
        """删除本地人员账号：清部门关系、角色（保留超管）、用户组，软删用户。"""
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import User
        from bisheng.user.domain.models.user_role import UserRole
        from bisheng.database.models.user_group import UserGroup

        await cls.acheck_local_member_delete(dept_id, user_id, login_user)
        counts = await cls._count_user_owned_data_assets(user_id)
        if sum(counts.values()) > 0:
            raise DepartmentMemberDeleteBlockedError(
                msg='User has data assets',
                counts=counts,
            )

        uds = await UserDepartmentDao.aget_user_departments(user_id)
        dept_ids = [int(u.department_id) for u in uds]

        async with get_async_db_session() as session:
            await session.exec(delete(UserDepartment).where(UserDepartment.user_id == user_id))
            await session.exec(
                delete(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id != AdminRole,
                ),
            )
            await session.exec(delete(UserGroup).where(UserGroup.user_id == user_id))
            db_user = (await session.exec(select(User).where(User.user_id == user_id))).first()
            if db_user:
                db_user.delete = 1
                session.add(db_user)
            await session.commit()

        if db_user:
            from bisheng.user.domain.services.user import UserService
            await UserService.ainvalidate_jwt_after_account_disabled(user_id)

        for did in dept_ids:
            ops = DepartmentChangeHandler.on_member_removed(did, user_id)
            await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def aget_member_edit_form(
        cls, dept_id: str, user_id: int, login_user,
    ) -> dict:
        """PRD 3.2.2：编辑人员弹窗数据（区分主属本地/第三方/兼职）。"""
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import UserDao
        from bisheng.user.domain.models.user_role import UserRoleDao
        from bisheng.database.models.user_group import UserGroupDao

        async with get_async_db_session() as session:
            ctx_dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if ctx_dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()
            mem = (
                await session.exec(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == ctx_dept.id,
                    )
                )
            ).first()
        if not mem:
            raise DepartmentMemberNotFoundError()

        user = await UserDao.aget_user(user_id)
        if not user or user.delete != 0:
            raise DepartmentMemberNotFoundError()

        old_roles = UserRoleDao.get_user_roles(user_id)
        role_ids_user = {int(r.role_id) for r in old_roles}
        if AdminRole in role_ids_user:
            raise DepartmentPermissionDeniedError()

        all_uds = await UserDepartmentDao.aget_user_departments(user_id)
        dept_int_ids = list({ud.department_id for ud in all_uds})
        depts = await DepartmentDao.aget_by_ids(dept_int_ids)
        dept_by_id = {d.id: d for d in depts}

        if mem.is_primary == 0:
            edit_mode = 'affiliate'
        elif getattr(user, 'source', 'local') == 'local':
            edit_mode = 'local_primary'
        else:
            edit_mode = 'synced_primary'

        catalog: dict = {}
        for d in depts:
            catalog[d.dept_id] = await cls.aget_assignable_roles(d.dept_id, login_user)

        primary_ud = next((x for x in all_uds if x.is_primary == 1), None)
        primary_block = None
        primary_role_ids: List[int] = []
        if primary_ud:
            pd = dept_by_id.get(primary_ud.department_id)
            if pd:
                ap = {int(r['id']) for r in catalog.get(pd.dept_id, [])}
                primary_role_ids = sorted(list(role_ids_user & ap))
                primary_block = {
                    'id': pd.id,
                    'dept_id': pd.dept_id,
                    'name': pd.name,
                    'role_ids': primary_role_ids,
                }

        affiliate_rows = []
        for ud in sorted(all_uds, key=lambda x: x.id or 0):
            if ud.is_primary != 0:
                continue
            d = dept_by_id.get(ud.department_id)
            if not d:
                continue
            ap = {int(r['id']) for r in catalog.get(d.dept_id, [])}
            affiliate_rows.append({
                'dept_id': d.dept_id,
                'name': d.name,
                'role_ids': sorted(list(role_ids_user & ap)),
            })

        ctx_assignable_ids = {int(r['id']) for r in catalog.get(ctx_dept.dept_id, [])}
        context_role_ids = sorted(list(role_ids_user & ctx_assignable_ids))

        ug_links = await UserGroupDao.aget_user_group(user_id)
        current_group_ids = [int(x.group_id) for x in ug_links]
        manageable_groups = await cls._manageable_group_options(login_user)

        return {
            'edit_mode': edit_mode,
            'user': {
                'user_id': user.user_id,
                'user_name': user.user_name,
                'person_id': cls._person_display_id(user),
                'source': getattr(user, 'source', 'local') or 'local',
            },
            'context': {
                'dept_id': ctx_dept.dept_id,
                'name': ctx_dept.name,
                'is_primary': int(mem.is_primary or 0),
            },
            'primary_department': primary_block,
            'affiliate_rows': affiliate_rows,
            'assignable_roles_catalog': catalog,
            'context_role_ids': context_role_ids,
            'manageable_groups': manageable_groups,
            'current_group_ids': current_group_ids,
            'can_change_primary': edit_mode == 'local_primary',
        }

    @classmethod
    async def aapply_member_edit(
        cls, dept_id: str, user_id: int, data: DepartmentMemberEditApply, login_user,
    ) -> None:
        """PRD 3.2.2：保存编辑（用户组合并替换 + 角色按部门可分配域合并）。"""
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import UserDao
        from bisheng.user.domain.models.user_role import UserRoleDao

        async with get_async_db_session() as session:
            ctx_dept = await _get_dept_and_check_permission(session, dept_id, login_user)
            if ctx_dept.status == 'archived':
                raise DepartmentArchivedReadonlyError()
            mem = (
                await session.exec(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == ctx_dept.id,
                    )
                )
            ).first()
        if not mem:
            raise DepartmentMemberNotFoundError()

        user = await UserDao.aget_user(user_id)
        if not user or user.delete != 0:
            raise DepartmentMemberNotFoundError()

        old_roles = UserRoleDao.get_user_roles(user_id)
        old_role_ids = [int(r.role_id) for r in old_roles]
        if AdminRole in old_role_ids:
            raise DepartmentPermissionDeniedError()

        role_ids_user = set(old_role_ids)

        if mem.is_primary == 0:
            edit_mode = 'affiliate'
        elif getattr(user, 'source', 'local') == 'local':
            edit_mode = 'local_primary'
        else:
            edit_mode = 'synced_primary'

        if data.user_name is not None and edit_mode == 'local_primary':
            name = (data.user_name or '').strip()
            if name and name != user.user_name:
                user.user_name = name
                await UserDao.aupdate_user(user)

        if edit_mode == 'local_primary' and data.primary_department_id is not None:
            async with get_async_db_session() as session:
                target = (
                    await session.exec(
                        select(Department).where(
                            Department.id == int(data.primary_department_id),
                        ),
                    )
                ).first()
            if not target:
                raise DepartmentNotFoundError()
            if not await cls._department_in_admin_writable_scope(login_user, target):
                raise DepartmentPermissionDeniedError()
            primary_row = await UserDepartmentDao.aget_user_primary_department(user_id)
            cur_pid = int(primary_row.department_id) if primary_row else None
            if cur_pid is None or cur_pid != int(target.id):
                await cls._apply_local_primary_department_change(user_id, int(target.id))

        if edit_mode != 'affiliate' and data.group_ids is not None:
            from bisheng.common.errcode.user_group import (
                UserGroupPermissionDeniedError,
            )
            from bisheng.user_group.domain.services.user_group_service import (
                UserGroupService,
            )

            req = [int(x) for x in data.group_ids]
            try:
                await UserGroupService.areplace_user_memberships(
                    user_id, req, login_user,
                )
            except UserGroupPermissionDeniedError:
                raise DepartmentPermissionDeniedError() from None

        if edit_mode == 'affiliate':
            a_ctx = await cls._assignable_role_id_set(ctx_dept.dept_id, login_user)
            picked = {int(x) for x in (data.context_role_ids or [])}
            if not picked.issubset(a_ctx):
                raise DepartmentInvalidRolesError()
            u_union = a_ctx
            new_roles = (role_ids_user - (role_ids_user & u_union)) | picked
        else:
            all_uds = await UserDepartmentDao.aget_user_departments(user_id)
            primary_ud = next((x for x in all_uds if x.is_primary == 1), None)
            if not primary_ud:
                raise DepartmentInvalidRolesError()
            depts = await DepartmentDao.aget_by_ids([d.department_id for d in all_uds])
            dept_by_id = {d.id: d for d in depts}
            pdept = dept_by_id.get(primary_ud.department_id)
            if not pdept:
                raise DepartmentInvalidRolesError()

            u_union: set = set()
            u_union |= await cls._assignable_role_id_set(pdept.dept_id, login_user)

            secondary_keys = []
            for ud in all_uds:
                if ud.is_primary != 0:
                    continue
                d = dept_by_id.get(ud.department_id)
                if not d:
                    continue
                secondary_keys.append(d.dept_id)
                u_union |= await cls._assignable_role_id_set(d.dept_id, login_user)

            pr = {int(x) for x in (data.primary_role_ids or [])}
            ap = await cls._assignable_role_id_set(pdept.dept_id, login_user)
            if not pr.issubset(ap):
                raise DepartmentInvalidRolesError()

            aff_rows = data.affiliate_roles or []
            aff_payload = {str(x.dept_id): [int(r) for r in x.role_ids] for x in aff_rows}
            if set(aff_payload.keys()) != set(secondary_keys):
                raise DepartmentInvalidRolesError()

            picked = set(pr)
            for dk, rlist in aff_payload.items():
                rs = {int(x) for x in rlist}
                a_set = await cls._assignable_role_id_set(dk, login_user)
                if not rs.issubset(a_set):
                    raise DepartmentInvalidRolesError()
                picked |= rs

            new_roles = (role_ids_user - (role_ids_user & u_union)) | picked

        if AdminRole in new_roles:
            raise DepartmentInvalidRolesError()

        need_add = sorted(new_roles - role_ids_user)
        need_del = sorted(role_ids_user - new_roles)
        if need_add:
            UserRoleDao.add_user_roles(user_id, need_add)
        if need_del:
            UserRoleDao.delete_user_roles(user_id, need_del)
        if need_add or need_del:
            await LegacyRBACSyncService.sync_user_role_change(
                user_id,
                role_ids_user,
                new_roles,
            )

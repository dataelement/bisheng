"""DepartmentService — core business logic for department tree management.

Part of F002-department-tree.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import List, Optional

from sqlalchemy import and_, delete, func, or_, update
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
    DepartmentNotFoundError,
    DepartmentOpenFGAUnavailableError,
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

logger = logging.getLogger(__name__)

# AdminRole = 1, same as bisheng.database.constants.AdminRole
_ADMIN_ROLE_ID = 1


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
        except Exception:
            logger.warning(
                'PermissionService.check failed for dept admin, user=%d dept=%d',
                login_user.user_id, dept_internal_id,
            )
    raise DepartmentPermissionDeniedError()


def _get_dept_id_prefix() -> str:
    from bisheng.common.services.config_service import settings
    prefix = settings.get_from_db('dept_id_prefix')
    return prefix if isinstance(prefix, str) and prefix else 'BS'


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

        return dept

    @classmethod
    async def aget_tree(cls, login_user) -> List[DepartmentTreeNode]:
        # System admin sees full tree; dept admin sees subtree only
        is_sys_admin = _is_admin(login_user)
        if not is_sys_admin:
            admin_depts = await DepartmentDao.aget_user_admin_departments(
                login_user.user_id,
            )
            if not admin_depts:
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

            # Filter to dept admin's subtree if not system admin
            if not is_sys_admin:
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

        return dept

    @classmethod
    async def adelete_department(cls, dept_id: str, login_user) -> None:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            # Check for children
            children = (await session.exec(
                select(Department).where(
                    Department.parent_id == dept.id,
                    Department.status == 'active',
                )
            )).first()
            if children:
                raise DepartmentHasChildrenError()

            # Check for members
            count_result = await session.exec(
                select(func.count(UserDepartment.id)).where(
                    UserDepartment.department_id == dept.id,
                )
            )
            if count_result.one() > 0:
                raise DepartmentHasMembersError()

            parent_id = dept.parent_id
            dept.status = 'archived'
            session.add(dept)
            await session.commit()

        # Fire change handler
        if parent_id is not None:
            ops = DepartmentChangeHandler.on_archived(dept.id, parent_id)
            await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def apurge_department(cls, dept_id: str, login_user) -> None:
        """Permanently delete an archived department and clean up all references."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            if dept.status != 'archived':
                raise DepartmentNotArchivedError()

            # Block if any child departments still reference this one
            child = (await session.exec(
                select(Department.id).where(
                    Department.parent_id == dept.id,
                )
            )).first()
            if child is not None:
                raise DepartmentHasChildrenError()

            dept_internal_id = dept.id

            # Collect member user_ids for OpenFGA cleanup
            member_rows = (await session.exec(
                select(UserDepartment.user_id).where(
                    UserDepartment.department_id == dept_internal_id,
                )
            )).all()
            member_user_ids = list(member_rows)

            # Delete UserDepartment records
            await session.exec(
                delete(UserDepartment).where(
                    UserDepartment.department_id == dept_internal_id,
                )
            )

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
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

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

    @classmethod
    async def aremove_member(
        cls, dept_id: str, user_id: int, login_user,
    ) -> None:
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

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

        # Fire change handler
        ops = DepartmentChangeHandler.on_member_removed(dept.id, user_id)
        await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def aget_admins(
        cls, dept_id: str, login_user,
    ) -> List[dict]:
        """Get admin users of a department from OpenFGA."""
        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

        from bisheng.core.openfga.manager import aget_fga_client
        fga = await aget_fga_client()
        if fga is None:
            return []
        try:
            tuples = await fga.read_tuples(
                relation='admin', object=f'department:{dept.id}',
            )
        except Exception:
            logger.warning('FGA read_tuples failed for department %s admins', dept_id)
            return []

        user_ids = []
        for t in tuples:
            # FGAClient.read_tuples returns OpenFGA tuple_key dicts: {user, relation, object}
            user_str = t.get('user', '') if isinstance(t, dict) else ''
            if not user_str and isinstance(t.get('key'), dict):
                user_str = t['key'].get('user', '')
            if user_str.startswith('user:'):
                try:
                    user_ids.append(int(user_str.split(':', 1)[1]))
                except ValueError:
                    continue

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

        if to_add or to_remove:
            from bisheng.core.openfga.manager import aget_fga_client
            if await aget_fga_client() is None:
                raise DepartmentOpenFGAUnavailableError()

        if to_add:
            ops = DepartmentChangeHandler.on_admin_set(dept.id, to_add)
            await DepartmentChangeHandler.execute_async(ops)
        if to_remove:
            ops = DepartmentChangeHandler.on_admin_removed(dept.id, to_remove)
            await DepartmentChangeHandler.execute_async(ops)

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

        def _last_modified(row) -> object:
            """成员行「修改时间」：取加入部门、用户创建、用户最近更新中的最晚时刻。"""
            times = [
                row.member_join_time,
                row.user_create_time,
                row.user_update_time,
            ]
            valid = [x for x in times if x is not None]
            return max(valid) if valid else None

        data = [
            {
                'user_id': r.user_id,
                'user_name': r.user_name,
                'department_id': r.department_id,
                'is_primary': r.is_primary,
                'source': r.source,
                'create_time': r.member_join_time,
                'update_time': _last_modified(r),
                'enabled': r.user_deleted == 0,
                'user_groups': user_groups_map.get(r.user_id, []),
                'roles': roles_map.get(r.user_id, []),
            }
            for r in rows
        ]
        return {'data': data, 'total': total}

    @classmethod
    async def aget_assignable_roles(
        cls, dept_id: str, login_user,
    ) -> List[dict]:
        """当前部门可授予的角色：全局 + 本部门子树内定义的角色（不含内置超管）。"""
        from bisheng.database.constants import AdminRole
        from bisheng.database.models.role import Role

        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

            subtree = await session.exec(
                select(Department.id).where(
                    Department.path.like(f'{dept.path}%'),
                    Department.status == 'active',
                )
            )
            raw_ids = subtree.all()
            subtree_ids = []
            for row in raw_ids:
                subtree_ids.append(int(row[0]) if isinstance(row, tuple) else int(row))

            stmt = select(Role).where(
                Role.id > AdminRole,
                or_(
                    Role.role_type == 'global',
                    and_(
                        Role.role_type == 'tenant',
                        Role.tenant_id == login_user.tenant_id,
                        or_(
                            Role.department_id.is_(None),
                            Role.department_id.in_(subtree_ids),
                        ),
                    ),
                    # 兼容旧数据：历史角色可能未写 role_type，默认按 tenant 角色处理
                    and_(
                        or_(Role.role_type.is_(None), Role.role_type == ''),
                        Role.tenant_id == login_user.tenant_id,
                        or_(
                            Role.department_id.is_(None),
                            Role.department_id.in_(subtree_ids),
                        ),
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
        from bisheng.common.errcode.user import UserNameAlreadyExistError
        from bisheng.database.constants import AdminRole
        from bisheng.user.domain.models.user import User, UserDao
        from bisheng.user.domain.services.user import UserService
        from bisheng.utils import md5_hash

        async with get_async_db_session() as session:
            dept = await _get_dept_and_check_permission(session, dept_id, login_user)

        plain = UserService.decrypt_password_plain(data.password)
        if not _password_meets_prd_policy(plain):
            raise DepartmentInvalidPasswordError()

        if await UserDao.aget_user_by_username(data.user_name):
            raise UserNameAlreadyExistError()

        assignable = await cls.aget_assignable_roles(dept_id, login_user)
        allowed_ids = {r['id'] for r in assignable}
        if AdminRole in data.role_ids or not set(data.role_ids).issubset(allowed_ids):
            raise DepartmentInvalidRolesError()

        person_id = None
        for _ in range(5):
            candidate = generate_dept_id(_get_dept_id_prefix())
            existing = await UserDao.aget_by_source_external_id('local', candidate)
            if not existing:
                person_id = candidate
                break
        if not person_id:
            person_id = f'BS@{secrets.token_hex(6)}'

        pwd_hash = md5_hash(plain)
        user = User(
            user_name=data.user_name,
            password=pwd_hash,
            source='local',
            external_id=person_id,
        )
        user = UserDao.add_user_with_groups_and_roles(
            user, [], list(data.role_ids),
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
        """Return groups the current user can actually mutate (admin or creator)."""
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        res = await UserGroupService.alist_groups(1, 2000, '', login_user)
        is_admin = login_user.is_admin() if callable(getattr(login_user, 'is_admin', None)) else False
        out = []
        for x in res.get('data') or []:
            if is_admin or x.get('create_user') == login_user.user_id:
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
        """将本地用户主部门切到 new_dept_id；原主部门行降为附属（is_primary=0）。"""
        fga_new_dept: Optional[int] = None
        async with get_async_db_session() as session:
            uds = list(
                (await session.exec(
                    select(UserDepartment).where(UserDepartment.user_id == user_id),
                )).all()
            )
            target_ud = next((u for u in uds if int(u.department_id) == int(new_dept_id)), None)
            for u in uds:
                if int(u.is_primary or 0) == 1:
                    u.is_primary = 0
                    session.add(u)
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
                fga_new_dept = int(new_dept_id)
            await session.commit()
        if fga_new_dept is not None:
            ops = DepartmentChangeHandler.on_members_added(fga_new_dept, [user_id])
            await DepartmentChangeHandler.execute_async(ops)

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
        from bisheng.user.domain.models.user import User, UserDao
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
        from bisheng.database.models.user_group import UserGroupDao
        from bisheng.common.errcode.user import UserNameAlreadyExistError

        async with get_async_db_session() as session:
            ctx_dept = await _get_dept_and_check_permission(session, dept_id, login_user)
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
                exists = await UserDao.aget_user_by_username(name)
                if exists and exists.user_id != user_id:
                    raise UserNameAlreadyExistError()
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
            mg = await cls._manageable_group_options(login_user)
            manageable = {int(x['id']) for x in mg}
            req = [int(x) for x in data.group_ids]
            if any(g not in manageable for g in req):
                raise DepartmentPermissionDeniedError()
            old_links = await UserGroupDao.aget_user_group(user_id)
            old_gids = [int(x.group_id) for x in old_links]
            preserved = [g for g in old_gids if g not in manageable]
            final_set = set(preserved) | set(req)
            to_remove = [g for g in old_gids if g not in final_set]
            to_add = [g for g in final_set if g not in old_gids]
            if to_remove:
                UserGroupDao.delete_user_groups(user_id, to_remove)
            if to_add:
                UserGroupDao.add_user_groups(user_id, to_add)

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

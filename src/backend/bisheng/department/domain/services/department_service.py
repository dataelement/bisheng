"""DepartmentService — core business logic for department tree management.

Part of F002-department-tree.
"""

from __future__ import annotations

import logging
import secrets
from typing import List, Optional

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.common.errcode.department import (
    DepartmentCircularMoveError,
    DepartmentHasChildrenError,
    DepartmentHasMembersError,
    DepartmentMemberExistsError,
    DepartmentMemberNotFoundError,
    DepartmentNameDuplicateError,
    DepartmentNotFoundError,
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
    DepartmentMemberAdd,
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


def generate_dept_id(prefix: str = 'BS') -> str:
    """Generate a business key like 'BS@a3f7e9'."""
    return f'{prefix}@{secrets.token_hex(3)}'


async def _get_dept_or_raise(session, dept_id: str) -> Department:
    """Look up department by business key, raise DepartmentNotFoundError if missing."""
    result = await session.exec(
        select(Department).where(Department.dept_id == dept_id)
    )
    dept = result.first()
    if not dept:
        raise DepartmentNotFoundError()
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
                candidate = generate_dept_id()
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
            # Get all active departments for current tenant
            result = await session.exec(
                select(Department).where(Department.status == 'active')
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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
    async def amove_department(
        cls, dept_id: str, data: DepartmentMoveRequest, login_user,
    ) -> Department:
        async with get_async_db_session() as session:
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
                dept_id = generate_dept_id()

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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

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
            user_str = t.get('key', {}).get('user', '')
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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

        # Get current admins from FGA
        current_admins = await cls.aget_admins(dept_id, login_user)
        current_ids = {a['user_id'] for a in current_admins}
        new_ids = set(user_ids)

        to_add = list(new_ids - current_ids)
        to_remove = list(current_ids - new_ids)

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
            dept = await _get_dept_or_raise(session, dept_id)
            await _check_permission(login_user, dept_internal_id=dept.id)

            from bisheng.user.domain.models.user import User

            base = (
                select(
                    UserDepartment.user_id,
                    User.user_name,
                    UserDepartment.department_id,
                    UserDepartment.is_primary,
                    UserDepartment.source,
                    UserDepartment.create_time,
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
                from bisheng.database.models.group import Group
                from bisheng.database.models.user_group import UserGroup
                ug_result = await session.exec(
                    select(
                        UserGroup.user_id,
                        Group.id,
                        Group.group_name,
                    )
                    .join(Group, UserGroup.group_id == Group.id)
                    .where(UserGroup.user_id.in_(user_ids))
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

        data = [
            {
                'user_id': r.user_id,
                'user_name': r.user_name,
                'department_id': r.department_id,
                'is_primary': r.is_primary,
                'source': r.source,
                'create_time': r.create_time,
                'enabled': r.user_deleted == 0,
                'user_groups': user_groups_map.get(r.user_id, []),
                'roles': roles_map.get(r.user_id, []),
            }
            for r in rows
        ]
        return {'data': data, 'total': total}

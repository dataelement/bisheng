"""UserGroupService — core business logic for user group management (F003)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from bisheng.common.errcode.user_group import (
    UserGroupMemberNotFoundError,
    UserGroupNameDuplicateError,
    UserGroupNoSeparateAdminsError,
    UserGroupNotFoundError,
    UserGroupPermissionDeniedError,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.group import Group, GroupDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user_group.domain.schemas.user_group_schema import (
    UserGroupCreate,
    UserGroupUpdate,
)
from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler

logger = logging.getLogger(__name__)

# AdminRole constant (id=1), matches F002 pattern
AdminRole = 1


def _sync_user_group_delete_side_effects(group_id: int) -> list[tuple[int, int, str]]:
    """与 RoleGroupService.delete_group_hook 对齐：资源授权迁移、组资源/组角色清理、网关 Redis 通知。"""
    import json

    from bisheng.core.cache.redis_manager import get_redis_client_sync
    from bisheng.database.models.group import GroupDao
    from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
    from bisheng.database.models.role import RoleDao
    from bisheng.database.models.user_group import UserGroupDao

    all_resource = GroupResourceDao.get_group_all_resource(group_id)
    fallback_gid = None
    for g in GroupDao.get_all_group():
        if g.id != group_id:
            fallback_gid = g.id
            break
    need_move_resource = []
    moved_resources = []
    for one in all_resource:
        resource_groups = GroupResourceDao.get_resource_group(
            ResourceTypeEnum(one.type), one.third_id,
        )
        if len(resource_groups) > 1:
            continue
        if fallback_gid is not None:
            moved_resources.append((int(fallback_gid), int(one.type), str(one.third_id)))
            one.group_id = str(fallback_gid)
            need_move_resource.append(one)
    if need_move_resource:
        GroupResourceDao.update_group_resource(need_move_resource)
    GroupResourceDao.delete_group_resource_by_group_id(group_id)
    RoleDao.delete_role_by_group_id(group_id)
    UserGroupDao.delete_group_all_admin(group_id)

    delete_message = json.dumps({'id': group_id})
    redis_client = get_redis_client_sync()
    redis_client.rpush('delete_group', delete_message, expiration=86400)
    redis_client.publish('delete_group', delete_message)
    return moved_resources


def _is_admin(login_user) -> bool:
    """Check if login_user has system admin role. Temporary until F004."""
    if hasattr(login_user, 'user_role') and isinstance(login_user.user_role, list):
        return AdminRole in login_user.user_role
    return False


async def _is_department_admin(login_user) -> bool:
    """True if user is admin of at least one department (OpenFGA)."""
    depts = await DepartmentDao.aget_user_admin_departments(login_user.user_id)
    return bool(depts)


async def _can_open_user_group_management(login_user) -> bool:
    """Who may use user-group management APIs: 超管 / 部门管理员 / 子租户管理员
    (PRD 3.2.2 + §4.5)."""
    if _is_admin(login_user):
        return True
    if await _is_department_admin(login_user):
        return True
    from bisheng.department.domain.services.department_service import (
        _is_tenant_admin,
    )
    return await _is_tenant_admin(login_user)


async def _user_can_view_group(login_user, group: Group) -> bool:
    """List/detail/members visibility (align with GroupDao.aget_visible_groups)."""
    if _is_admin(login_user):
        return True
    if group.visibility == 'public':
        return True
    if group.create_user == login_user.user_id:
        return True
    visible_ids_raw = await UserGroupDao.aget_user_visible_group_ids(login_user.user_id)
    visible_ids: Set[int] = set()
    for x in visible_ids_raw:
        visible_ids.add(int(x[0]) if isinstance(x, tuple) else int(x))
    return group.id in visible_ids


async def _ensure_manage_user_groups(login_user) -> None:
    if not await _can_open_user_group_management(login_user):
        raise UserGroupPermissionDeniedError()


async def _ensure_mutate_group(login_user, group: Group) -> None:
    """修改用户组元数据（名称、可见性等）：仅系统超管或创建者。"""
    if _is_admin(login_user):
        return
    if group.create_user == login_user.user_id:
        return
    raise UserGroupPermissionDeniedError()


async def _ensure_mutate_group_members(login_user, group: Group) -> None:
    """增删普通成员：超管、创建者，或「公开组」下的部门管理员（与组织成员编辑 PRD 一致）。"""
    if _is_admin(login_user):
        return
    if group.create_user == login_user.user_id:
        return
    if getattr(group, 'visibility', None) == 'public' and await _is_department_admin(login_user):
        return
    raise UserGroupPermissionDeniedError()


async def _ensure_create_group(login_user) -> None:
    await _ensure_manage_user_groups(login_user)


async def _ensure_delete_group(login_user, group: Group) -> None:
    """超管可删任意组；创建者可删自己创建的组（可有成员，删除后成员关系与组权限一并清理）。"""
    if _is_admin(login_user):
        return
    if group.create_user == login_user.user_id:
        return
    raise UserGroupPermissionDeniedError()


def _normalize_id_rows(raw: List) -> Set[int]:
    """Normalize SQLAlchemy/SQLModel scalar query rows to a set of ints."""
    out: Set[int] = set()
    for x in raw or []:
        if x is None:
            continue
        if isinstance(x, (list, tuple)):
            out.add(int(x[0]))
        else:
            out.add(int(x))
    return out


class UserGroupService:
    """User group business logic. All methods are async classmethods."""

    @classmethod
    async def _list_manageable_groups(cls, login_user) -> List[Group]:
        """Groups whose **membership** the caller may assign (编辑人员用户组多选).

        System admins: any group. Department admins: public groups + groups they
        created (private groups created by others remain out of scope). Other
        users: only groups they created.
        """
        if _is_admin(login_user):
            groups, _ = await GroupDao.aget_all_groups(1, 2000, '')
            return groups

        visible_groups, _ = await GroupDao.aget_visible_groups(
            login_user.user_id, 1, 2000, '',
        )
        if await _is_department_admin(login_user):
            return [
                g for g in visible_groups
                if g.visibility == 'public' or g.create_user == login_user.user_id
            ]
        return [g for g in visible_groups if g.create_user == login_user.user_id]

    @classmethod
    async def alist_manageable_groups(
        cls, login_user,
    ) -> List[Dict[str, Any]]:
        groups = await cls._list_manageable_groups(login_user)
        return [await cls._enrich_group(g) for g in groups]

    @classmethod
    async def _department_path_label(cls, user_id: int) -> str:
        """主属部门在组织树中的完整路径（用于 PRD 3.2.2 组内成员展示）。"""
        uds = await UserDepartmentDao.aget_user_departments(user_id)
        if not uds:
            return ''
        primary = next((x for x in uds if getattr(x, 'is_primary', 0) == 1), uds[0])
        dept = await DepartmentDao.aget_by_id(primary.department_id)
        if not dept or not dept.path:
            return dept.name if dept else ''
        ids: List[int] = []
        for seg in dept.path.strip('/').split('/'):
            if seg.isdigit():
                ids.append(int(seg))
        if not ids:
            return dept.name
        chain = await DepartmentDao.aget_by_ids(ids)
        id_to_name = {d.id: d.name for d in chain}
        parts = [id_to_name.get(i, '') for i in ids]
        return ' / '.join(p for p in parts if p)

    @classmethod
    async def acreate_group(
        cls, data: UserGroupCreate, login_user,
    ) -> Dict[str, Any]:
        await _ensure_create_group(login_user)

        # Check name uniqueness within tenant
        if await GroupDao.acheck_name_duplicate(data.group_name):
            raise UserGroupNameDuplicateError()

        group = Group(
            group_name=data.group_name,
            visibility=data.visibility,
            remark=data.remark,
            create_user=login_user.user_id,
            update_user=login_user.user_id,
        )
        group = await GroupDao.acreate(group)

        # Keep legacy user_group admin rows in sync for older auth/read paths.
        await UserGroupDao.aset_admins_batch(
            group.id, add_ids=[login_user.user_id], remove_ids=[],
        )

        # Emit OpenFGA tuple operations while retaining a legacy admin row for compatibility.
        ops = GroupChangeHandler.on_created(group.id, login_user.user_id)
        await GroupChangeHandler.execute_async(ops)

        return await cls._enrich_group(group)

    @classmethod
    async def alist_groups(
        cls, page: int, limit: int, keyword: str, login_user,
    ) -> Dict[str, Any]:
        if _is_admin(login_user):
            groups, total = await GroupDao.aget_all_groups(page, limit, keyword)
        else:
            groups, total = await GroupDao.aget_visible_groups(
                login_user.user_id, page, limit, keyword,
            )

        items = await cls._enrich_groups(groups)
        return {'data': items, 'total': total}

    @classmethod
    async def aget_group(
        cls, group_id: int, login_user,
    ) -> Dict[str, Any]:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        if not await _user_can_view_group(login_user, group):
            raise UserGroupPermissionDeniedError()

        return await cls._enrich_group(group)

    @classmethod
    async def aupdate_group(
        cls, group_id: int, data: UserGroupUpdate, login_user,
    ) -> Dict[str, Any]:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()
        await _ensure_mutate_group(login_user, group)

        # Check name uniqueness if name is being changed
        if data.group_name is not None and data.group_name != group.group_name:
            if await GroupDao.acheck_name_duplicate(
                data.group_name, exclude_id=group_id,
            ):
                raise UserGroupNameDuplicateError()

        # Update non-None fields
        if data.group_name is not None:
            group.group_name = data.group_name
        if data.visibility is not None:
            group.visibility = data.visibility
        if data.remark is not None:
            group.remark = data.remark
        group.update_user = login_user.user_id

        group = await GroupDao.aupdate(group)
        return await cls._enrich_group(group)

    @classmethod
    async def adelete_group(cls, group_id: int, login_user) -> None:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        await _ensure_delete_group(login_user, group)

        from bisheng.permission.domain.services.owner_service import OwnerService
        from bisheng.permission.domain.services.legacy_rbac_sync_service import (
            LegacyRBACSyncService,
        )
        from bisheng.database.models.role import RoleDao

        await OwnerService.delete_resource_tuples('user_group', str(group_id))
        await LegacyRBACSyncService.cleanup_user_group_subject_tuples(group_id)
        for role in RoleDao.get_role_by_groups([group_id], '', 0, 0):
            await LegacyRBACSyncService.sync_role_deleted(role.id)
        moved_resources = _sync_user_group_delete_side_effects(group_id)
        for fallback_gid, resource_type, third_id in moved_resources:
            await LegacyRBACSyncService.sync_group_resource_move(
                group_id,
                fallback_gid,
                resource_type,
                third_id,
            )

        await GroupDao.adelete(group_id)

        ops = GroupChangeHandler.on_deleted(group_id)
        await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def aget_members(
        cls, group_id: int, page: int, limit: int, keyword: str,
        login_user,
    ) -> Dict[str, Any]:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        if not await _user_can_view_group(login_user, group):
            raise UserGroupPermissionDeniedError()

        members, total = await UserGroupDao.aget_group_members(
            group_id, page, limit, keyword,
        )
        for m in members:
            m['department_path'] = await cls._department_path_label(m['user_id'])
        return {'data': members, 'total': total}

    @classmethod
    async def aadd_members(
        cls, group_id: int, user_ids: List[int], login_user,
    ) -> None:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()
        await _ensure_mutate_group_members(login_user, group)

        if not user_ids:
            return

        raw_existing = await UserGroupDao.acheck_members_exist(group_id, user_ids)
        existing = _normalize_id_rows(raw_existing)
        to_add = [uid for uid in user_ids if uid not in existing]
        if not to_add:
            return

        await UserGroupDao.aadd_members_batch(group_id, to_add)

        ops = GroupChangeHandler.on_members_added(group_id, to_add)
        await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def async_plain_members(
        cls, group_id: int, desired_user_ids: List[int], login_user,
    ) -> None:
        """将普通成员全量同步为 desired_user_ids（与 UI 多选一致，避免前后端 diff 漂移）。"""
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()
        await _ensure_mutate_group_members(login_user, group)

        desired_set = {int(x) for x in desired_user_ids if x and int(x) > 0}
        current_ids = set(await UserGroupDao.aget_plain_member_user_ids(group_id))

        to_remove = sorted(current_ids - desired_set)
        to_add = sorted(desired_set - current_ids)

        if to_remove:
            ops = []
            for uid in to_remove:
                ops.extend(GroupChangeHandler.on_member_removed(group_id, uid))
            await UserGroupDao.adelete_plain_members_batch(group_id, to_remove)
            await GroupChangeHandler.execute_async(ops)

        if to_add:
            await UserGroupDao.aadd_members_batch(group_id, to_add)
            ops = GroupChangeHandler.on_members_added(group_id, to_add)
            await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def areplace_user_memberships(
        cls, user_id: int, desired_group_ids: List[int], login_user,
    ) -> None:
        """Replace memberships only within the caller's manageable groups.

        Memberships in groups outside the caller's mutation scope are preserved.
        """
        manageable_groups = await cls._list_manageable_groups(login_user)
        manageable_ids = {int(g.id) for g in manageable_groups}
        desired_ids = {int(gid) for gid in desired_group_ids if int(gid) > 0}

        if not desired_ids.issubset(manageable_ids):
            raise UserGroupPermissionDeniedError()

        current_links = await UserGroupDao.aget_user_group(user_id)
        current_ids = {int(link.group_id) for link in current_links}
        current_manageable_ids = current_ids & manageable_ids

        to_remove = sorted(current_manageable_ids - desired_ids)
        to_add = sorted(desired_ids - current_manageable_ids)

        for group_id in to_remove:
            await cls.aremove_member(group_id, user_id, login_user)

        for group_id in to_add:
            await cls.aadd_members(group_id, [user_id], login_user)

    @classmethod
    async def aremove_member(
        cls, group_id: int, user_id: int, login_user,
    ) -> None:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()
        await _ensure_mutate_group_members(login_user, group)

        row = await UserGroupDao.aget_plain_member_row(group_id, user_id)
        if not row:
            raise UserGroupMemberNotFoundError()

        await UserGroupDao.aremove_member(group_id, user_id)

        ops = GroupChangeHandler.on_member_removed(group_id, user_id)
        await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def aset_admins(
        cls, group_id: int, _user_ids: List[int], login_user,
    ) -> List[Dict]:
        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()
        await _ensure_mutate_group(login_user, group)
        raise UserGroupNoSeparateAdminsError()

    # --- Private helpers ---

    @classmethod
    async def _enrich_group(cls, group: Group) -> Dict[str, Any]:
        """Attach member_count、创建者展示（不再使用 user_group 管理员多选）。"""
        member_count = await UserGroupDao.aget_group_member_count(group.id)
        creator_name = ''
        if group.create_user:
            u = await UserDao.aget_user(group.create_user)
            creator_name = u.user_name if u else str(group.create_user)
        group_admins = (
            [{'user_id': group.create_user, 'user_name': creator_name}]
            if group.create_user
            else []
        )
        return {
            'id': group.id,
            'group_name': group.group_name,
            'visibility': group.visibility,
            'remark': group.remark,
            'member_count': member_count,
            'create_user': group.create_user,
            'create_user_name': creator_name or None,
            'create_time': group.create_time,
            'update_time': group.update_time,
            'group_admins': group_admins,
        }

    @classmethod
    async def _enrich_groups(cls, groups: List[Group]) -> List[Dict[str, Any]]:
        """列表页批量补充成员数和创建者名称，避免逐条查询。"""
        if not groups:
            return []

        group_ids = [int(group.id) for group in groups if group.id is not None]
        member_counts = await UserGroupDao.aget_group_member_counts(group_ids)

        creator_ids = sorted({
            int(group.create_user) for group in groups if group.create_user
        })
        creator_name_map: Dict[int, str] = {}
        if creator_ids:
            creators = await UserDao.aget_user_by_ids(creator_ids)
            creator_name_map = {
                int(user.user_id): user.user_name
                for user in creators
                if user.user_id is not None
            }

        items: List[Dict[str, Any]] = []
        for group in groups:
            creator_name = ''
            if group.create_user:
                creator_name = creator_name_map.get(int(group.create_user), str(group.create_user))
            items.append({
                'id': group.id,
                'group_name': group.group_name,
                'visibility': group.visibility,
                'remark': group.remark,
                'member_count': member_counts.get(int(group.id), 0) if group.id is not None else 0,
                'create_user': group.create_user,
                'create_user_name': creator_name or None,
                'create_time': group.create_time,
                'update_time': group.update_time,
                'group_admins': (
                    [{'user_id': group.create_user, 'user_name': creator_name}]
                    if group.create_user else []
                ),
            })
        return items

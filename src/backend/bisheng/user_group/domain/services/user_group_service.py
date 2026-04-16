"""UserGroupService — core business logic for user group management (F003)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from bisheng.common.errcode.user_group import (
    UserGroupHasMembersError,
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
    """Who may use user-group management APIs (PRD 3.2.2): 超管 / 部门管理员。"""
    if _is_admin(login_user):
        return True
    return await _is_department_admin(login_user)


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
    """更新成员等：仅系统超管或该用户组的创建者。"""
    if _is_admin(login_user):
        return
    if group.create_user == login_user.user_id:
        return
    raise UserGroupPermissionDeniedError()


async def _ensure_create_group(login_user) -> None:
    await _ensure_manage_user_groups(login_user)


async def _ensure_delete_group(login_user, group: Group) -> None:
    """超管可删任意空组；创建者可删自己创建的空组。"""
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
        """Groups the caller may mutate.

        System admins may manage any group. Non-admins may only manage
        groups they created themselves.
        """
        if _is_admin(login_user):
            groups, _ = await GroupDao.aget_all_groups(1, 2000, '')
            return groups

        visible_groups, _ = await GroupDao.aget_visible_groups(
            login_user.user_id, 1, 2000, '',
        )
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

        requested_admin_ids = {
            int(uid) for uid in (data.admin_user_ids or [])
            if uid is not None
        }
        extra_admin_ids = requested_admin_ids - {int(login_user.user_id)}
        if extra_admin_ids:
            raise UserGroupNoSeparateAdminsError()

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

        items = []
        for g in groups:
            items.append(await cls._enrich_group(g))

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

        member_count = await UserGroupDao.aget_group_member_count(group_id)
        if member_count > 0:
            raise UserGroupHasMembersError()

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
        await _ensure_mutate_group(login_user, group)

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
        await _ensure_mutate_group(login_user, group)

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
        await _ensure_mutate_group(login_user, group)

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

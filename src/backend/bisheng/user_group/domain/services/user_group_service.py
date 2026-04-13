"""UserGroupService — core business logic for user group management (F003)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bisheng.common.errcode.user_group import (
    UserGroupDefaultProtectedError,
    UserGroupHasMembersError,
    UserGroupMemberExistsError,
    UserGroupMemberNotFoundError,
    UserGroupNameDuplicateError,
    UserGroupNotFoundError,
    UserGroupPermissionDeniedError,
)
from bisheng.database.models.group import DefaultGroup, Group, GroupDao
from bisheng.database.models.user_group import UserGroupDao
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


def _check_permission(login_user) -> None:
    """Raise UserGroupPermissionDeniedError if not admin."""
    if not _is_admin(login_user):
        raise UserGroupPermissionDeniedError()


class UserGroupService:
    """User group business logic. All methods are async classmethods."""

    @classmethod
    async def acreate_group(
        cls, data: UserGroupCreate, login_user,
    ) -> Dict[str, Any]:
        _check_permission(login_user)

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

        # Ensure creator is always an admin (for visibility in user_group table)
        admin_ids = list(data.admin_user_ids) if data.admin_user_ids else []
        if login_user.user_id not in admin_ids:
            admin_ids.append(login_user.user_id)

        await UserGroupDao.aset_admins_batch(
            group.id, add_ids=admin_ids, remove_ids=[],
        )

        # Emit OpenFGA tuple operations
        ops = GroupChangeHandler.on_created(group.id, login_user.user_id)
        await GroupChangeHandler.execute_async(ops)
        extra_admin_ids = [uid for uid in admin_ids if uid != login_user.user_id]
        if extra_admin_ids:
            ops = GroupChangeHandler.on_admin_set(group.id, extra_admin_ids)
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

        # Visibility check for non-admin
        if group.visibility == 'private' and not _is_admin(login_user):
            user_group_ids = await UserGroupDao.aget_user_visible_group_ids(
                login_user.user_id,
            )
            if group.id not in user_group_ids:
                raise UserGroupPermissionDeniedError()

        return await cls._enrich_group(group)

    @classmethod
    async def aupdate_group(
        cls, group_id: int, data: UserGroupUpdate, login_user,
    ) -> Dict[str, Any]:
        _check_permission(login_user)

        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        # Default group cannot be renamed
        if group_id == DefaultGroup and data.group_name is not None and data.group_name != group.group_name:
            raise UserGroupDefaultProtectedError()

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
        _check_permission(login_user)

        if group_id == DefaultGroup:
            raise UserGroupDefaultProtectedError()

        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

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

        # Visibility check
        if group.visibility == 'private' and not _is_admin(login_user):
            user_group_ids = await UserGroupDao.aget_user_visible_group_ids(
                login_user.user_id,
            )
            if group.id not in user_group_ids:
                raise UserGroupPermissionDeniedError()

        members, total = await UserGroupDao.aget_group_members(
            group_id, page, limit, keyword,
        )
        return {'data': members, 'total': total}

    @classmethod
    async def aadd_members(
        cls, group_id: int, user_ids: List[int], login_user,
    ) -> None:
        _check_permission(login_user)

        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        existing = await UserGroupDao.acheck_members_exist(group_id, user_ids)
        if existing:
            raise UserGroupMemberExistsError()

        await UserGroupDao.aadd_members_batch(group_id, user_ids)

        ops = GroupChangeHandler.on_members_added(group_id, user_ids)
        await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def aremove_member(
        cls, group_id: int, user_id: int, login_user,
    ) -> None:
        _check_permission(login_user)

        existing = await UserGroupDao.acheck_members_exist(group_id, [user_id])
        if not existing:
            raise UserGroupMemberNotFoundError()

        await UserGroupDao.aremove_member(group_id, user_id)

        ops = GroupChangeHandler.on_member_removed(group_id, user_id)
        await GroupChangeHandler.execute_async(ops)

    @classmethod
    async def aset_admins(
        cls, group_id: int, user_ids: List[int], login_user,
    ) -> List[Dict]:
        _check_permission(login_user)

        group = await GroupDao.aget_by_id(group_id)
        if not group:
            raise UserGroupNotFoundError()

        current_admins = await UserGroupDao.aget_group_admins_detail(group_id)
        current_ids = {a['user_id'] for a in current_admins}
        new_ids = set(user_ids)

        to_add = list(new_ids - current_ids)
        to_remove = list(current_ids - new_ids)

        await UserGroupDao.aset_admins_batch(group_id, to_add, to_remove)

        if to_add:
            ops = GroupChangeHandler.on_admin_set(group_id, to_add)
            await GroupChangeHandler.execute_async(ops)
        if to_remove:
            ops = GroupChangeHandler.on_admin_removed(group_id, to_remove)
            await GroupChangeHandler.execute_async(ops)

        return await UserGroupDao.aget_group_admins_detail(group_id)

    @classmethod
    async def acreate_default_group(
        cls, tenant_id: int, creator_user_id: int,
    ) -> Group:
        """Create default user group for a tenant. Used by init_data / F010.

        Idempotent: returns existing default group if one already exists for the tenant.
        """
        from sqlmodel import select
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                # Check if default group already exists for this tenant
                existing = (await session.exec(
                    select(Group).where(
                        Group.tenant_id == tenant_id,
                        Group.group_name == 'Default user group',
                    )
                )).first()
                if existing:
                    return existing

                group = Group(
                    group_name='Default user group',
                    visibility='public',
                    tenant_id=tenant_id,
                    create_user=creator_user_id,
                    update_user=creator_user_id,
                )
                session.add(group)
                await session.flush()
                await session.refresh(group)
                await session.commit()
                return group

    # --- Private helpers ---

    @classmethod
    async def _enrich_group(cls, group: Group) -> Dict[str, Any]:
        """Attach member_count and group_admins to a group dict."""
        member_count = await UserGroupDao.aget_group_member_count(group.id)
        admins = await UserGroupDao.aget_group_admins_detail(group.id)
        return {
            'id': group.id,
            'group_name': group.group_name,
            'visibility': group.visibility,
            'remark': group.remark,
            'member_count': member_count,
            'create_user': group.create_user,
            'create_time': group.create_time,
            'update_time': group.update_time,
            'group_admins': admins,
        }

from __future__ import annotations

from typing import List

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelGrantItem,
)
from bisheng.common.repositories.interfaces.space_channel_member_repository import (
    SpaceChannelMemberRepository,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.user_group import UserGroupDao


class ChannelMembershipSyncService:
    def __init__(self, space_channel_member_repository: SpaceChannelMemberRepository):
        self.space_channel_member_repository = space_channel_member_repository

    async def sync_grant(
        self,
        *,
        channel_id: str,
        grant: ChannelGrantItem,
        binding_key: str,
    ) -> List[int]:
        user_ids = await self._expand_subject_users(grant)
        if hasattr(self.space_channel_member_repository, 'delete_channel_membership_source_users_not_in'):
            await self.space_channel_member_repository.delete_channel_membership_source_users_not_in(
                channel_id=channel_id,
                grant_binding_key=binding_key,
                user_ids=user_ids,
            )
        for user_id in user_ids:
            await self.space_channel_member_repository.upsert_channel_membership_source(
                channel_id=channel_id,
                user_id=user_id,
                relation=grant.relation,
                grant_subject_type=grant.subject_type,
                grant_subject_id=grant.subject_id,
                grant_relation=grant.relation,
                grant_include_children=bool(grant.include_children),
                grant_model_id=grant.model_id,
                grant_binding_key=binding_key,
            )
        return user_ids

    async def sync_revoke(self, *, channel_id: str, binding_key: str) -> int:
        return await self.space_channel_member_repository.delete_channel_membership_source(
            channel_id,
            binding_key,
        )

    async def _expand_subject_users(self, grant: ChannelGrantItem) -> List[int]:
        if grant.subject_type == 'user':
            return [int(grant.subject_id)]
        if grant.subject_type == 'user_group':
            user_ids = await UserGroupDao.aget_plain_member_user_ids(int(grant.subject_id))
            return sorted({int(uid) for uid in user_ids})
        if grant.subject_type == 'department':
            department_ids = [int(grant.subject_id)]
            if grant.include_children:
                dept = await DepartmentDao.aget_by_id(int(grant.subject_id))
                if dept and getattr(dept, 'path', None):
                    department_ids = await DepartmentDao.aget_subtree_ids(dept.path)
            user_ids: set[int] = set()
            for dept_id in department_ids:
                dept_user_ids = await UserDepartmentDao.aget_user_ids_by_department(int(dept_id))
                user_ids.update(int(uid) for uid in dept_user_ids)
            return sorted(user_ids)
        return []

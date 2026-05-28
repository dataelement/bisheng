from typing import List, Optional

from sqlalchemy import case, func
from sqlmodel import select, col, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    SpaceChannelMember,
    BusinessTypeEnum,
    CHANNEL_RELATION_PRIORITY,
    CHANNEL_ROLE_TO_RELATION,
    ChannelRelationEnum,
    UserRoleEnum,
    MembershipStatusEnum,
    legacy_role_for_channel_relation,
    resolve_channel_relation,
)
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.user.domain.models.user import User


class SpaceChannelMemberRepositoryImpl(BaseRepositoryImpl[SpaceChannelMember, int], SpaceChannelMemberRepository):
    """SpaceChannelMember repository implementation for managing space and channel memberships."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SpaceChannelMember)

    @staticmethod
    def _relation_for_member(member: SpaceChannelMember) -> ChannelRelationEnum:
        return resolve_channel_relation(member) or ChannelRelationEnum.VIEWER

    @classmethod
    def _relation_rank(cls, member: SpaceChannelMember) -> int:
        return CHANNEL_RELATION_PRIORITY.get(cls._relation_for_member(member), 0)

    @classmethod
    def _highest_membership(cls, rows: List[SpaceChannelMember]) -> Optional[SpaceChannelMember]:
        if not rows:
            return None
        return max(rows, key=cls._relation_rank)

    @staticmethod
    def _roles_to_relations(roles: List[UserRoleEnum]) -> List[ChannelRelationEnum]:
        relations: List[ChannelRelationEnum] = []
        for role in roles:
            relation = CHANNEL_ROLE_TO_RELATION.get(UserRoleEnum(role))
            if relation:
                relations.append(relation)
        return relations

    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
                         relation: Optional[ChannelRelationEnum] = None,
                         grant_subject_type: Optional[str] = None,
                         grant_subject_id: Optional[int] = None,
                         grant_relation: Optional[ChannelRelationEnum] = None,
                         grant_include_children: bool = False,
                         grant_model_id: Optional[str] = None,
                         grant_binding_key: Optional[str] = None) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        if business_type == BusinessTypeEnum.CHANNEL and relation is None:
            relation = CHANNEL_ROLE_TO_RELATION.get(UserRoleEnum(role))
        new_member = SpaceChannelMember(
            business_id=business_id,
            business_type=business_type,
            user_id=user_id,
            user_role=role,
            status=status,
            relation=relation,
            grant_subject_type=grant_subject_type,
            grant_subject_id=grant_subject_id,
            grant_relation=grant_relation or relation,
            grant_include_children=grant_include_children,
            grant_model_id=grant_model_id,
            grant_binding_key=grant_binding_key,
        )
        new_member = await self.save(new_member)
        return new_member

    async def find_channel_memberships(self, user_id: int, roles: List[UserRoleEnum],
                                       statuses: Optional[List[MembershipStatusEnum]] = None) -> List[SpaceChannelMember]:
        """Get all channel memberships for a user filtered by roles and status."""
        if statuses is None:
            statuses = [MembershipStatusEnum.ACTIVE]

        query = select(SpaceChannelMember).where(
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            col(SpaceChannelMember.status).in_(statuses),
        )
        role_relations = self._roles_to_relations(roles)
        query = query.where(
            (col(SpaceChannelMember.user_role).in_(roles))
            | (col(SpaceChannelMember.relation).in_(role_relations))
        )
        result = await self.session.exec(query)
        rows = list(result.all())
        highest_by_channel: dict[str, SpaceChannelMember] = {}
        for row in rows:
            current = highest_by_channel.get(row.business_id)
            if current is None or self._relation_rank(row) > self._relation_rank(current):
                highest_by_channel[row.business_id] = row
        return list(highest_by_channel.values())

    async def find_membership(self, business_id: str, business_type: BusinessTypeEnum,
                              user_id: int) -> Optional[SpaceChannelMember]:
        """Find a specific membership by business ID, type, and user ID."""
        query = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == business_id,
            SpaceChannelMember.business_type == business_type,
            SpaceChannelMember.user_id == user_id
        )
        if business_type == BusinessTypeEnum.CHANNEL:
            query = query.where(SpaceChannelMember.status == MembershipStatusEnum.ACTIVE)
        result = await self.session.exec(query)
        rows = list(result.all())
        if business_type == BusinessTypeEnum.CHANNEL:
            return self._highest_membership(rows)
        return rows[0] if rows else None

    async def update_pin_status(self, member_id: int, is_pinned: bool) -> Optional[SpaceChannelMember]:
        """Update the pin status of a channel membership."""
        member = await self.find_by_id(member_id)
        if member:
            member.is_pinned = is_pinned
            member = await self.update(member)
        return member

    async def find_channel_members_paginated(self, channel_id: str, user_ids: Optional[List[int]] = None,
                                             page: int = 1, page_size: int = 20) -> List[SpaceChannelMember]:
        """获取频道成员分页列表，按角色和用户名排序：创建者最顶部、管理员其次按用户名排序、普通成员按用户名排序"""
        role_order = case(
            (SpaceChannelMember.relation == ChannelRelationEnum.OWNER, 0),
            (SpaceChannelMember.relation == ChannelRelationEnum.MANAGER, 1),
            (SpaceChannelMember.relation == ChannelRelationEnum.EDITOR, 2),
            (SpaceChannelMember.user_role == UserRoleEnum.CREATOR, 0),
            (SpaceChannelMember.user_role == UserRoleEnum.ADMIN, 1),
            else_=3
        )

        query = select(SpaceChannelMember).join(
            User, SpaceChannelMember.user_id == User.user_id
        ).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )

        if user_ids is not None:
            query = query.where(col(SpaceChannelMember.user_id).in_(user_ids))

        # 排序：先按角色(创建者>管理员>普通成员)，再按用户名首字母排序
        query = query.order_by(role_order, User.user_name.asc())

        result = await self.session.exec(query)
        rows = list(result.all())
        highest_by_user: dict[int, SpaceChannelMember] = {}
        for row in rows:
            current = highest_by_user.get(row.user_id)
            if current is None or self._relation_rank(row) > self._relation_rank(current):
                highest_by_user[row.user_id] = row
        deduped = list(highest_by_user.values())
        deduped.sort(key=lambda row: (-self._relation_rank(row), row.user_id))
        start = (page - 1) * page_size
        return deduped[start:start + page_size]

    async def count_channel_members(self, channel_id: str,
                                    user_ids: Optional[List[int]] = None) -> int:
        """Count the total number of channel members, optionally filtered by user IDs."""
        query = select(func.count(func.distinct(SpaceChannelMember.user_id))).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
        )

        if user_ids is not None:
            query = query.where(col(SpaceChannelMember.user_id).in_(user_ids))

        result = await self.session.exec(query)
        return result.one()

    async def find_members_by_role(self, channel_id: str, role: UserRoleEnum) -> List[SpaceChannelMember]:
        """按角色查询频道成员"""
        relation = CHANNEL_ROLE_TO_RELATION.get(UserRoleEnum(role))
        query = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )
        if relation:
            query = query.where(
                (SpaceChannelMember.user_role == role)
                | (SpaceChannelMember.relation == relation)
            )
        else:
            query = query.where(SpaceChannelMember.user_role == role)
        result = await self.session.exec(query)
        rows = list(result.all())
        highest_by_user: dict[int, SpaceChannelMember] = {}
        for row in rows:
            current = highest_by_user.get(row.user_id)
            if current is None or self._relation_rank(row) > self._relation_rank(current):
                highest_by_user[row.user_id] = row
        return list(highest_by_user.values())

    async def remove_non_creator_members(self, channel_id: str) -> None:
        """Remove all members from a channel except the creator (hard delete)."""
        from sqlmodel import delete
        query = (
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.user_role != UserRoleEnum.CREATOR,
                (SpaceChannelMember.relation.is_(None))
                | (SpaceChannelMember.relation != ChannelRelationEnum.OWNER)
            )
        )
        await self.session.exec(query)
        await self.session.commit()

    async def remove_rejected_members(self, channel_id: str) -> None:
        """Remove all rejected members from a channel."""
        from sqlmodel import delete
        query = (
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.status == MembershipStatusEnum.REJECTED,
            )
        )
        await self.session.exec(query)
        await self.session.commit()

    async def activate_pending_members(self, channel_id: str) -> int:
        """Activate all pending members of a channel (set status to True).

        Returns the number of members activated.
        """
        from sqlalchemy import update
        query = (
            update(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.status == MembershipStatusEnum.PENDING
            )
            .values(status=MembershipStatusEnum.ACTIVE)
        )
        result = await self.session.exec(query)
        await self.session.commit()
        return result.rowcount

    async def get_effective_channel_relation(self, channel_id: str, user_id: int) -> Optional[ChannelRelationEnum]:
        member = await self.find_membership(channel_id, BusinessTypeEnum.CHANNEL, user_id)
        if not member:
            return None
        return self._relation_for_member(member)

    async def find_channel_membership_sources(self, channel_id: str, user_id: int) -> List[SpaceChannelMember]:
        query = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def upsert_channel_membership_source(
        self,
        channel_id: str,
        user_id: int,
        relation: ChannelRelationEnum,
        grant_subject_type: str,
        grant_subject_id: Optional[int] = None,
        grant_relation: Optional[ChannelRelationEnum] = None,
        grant_include_children: bool = False,
        grant_model_id: Optional[str] = None,
        grant_binding_key: Optional[str] = None,
        status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
    ) -> SpaceChannelMember:
        relation = ChannelRelationEnum(relation)
        grant_relation = ChannelRelationEnum(grant_relation or relation)
        lookup = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.user_id == user_id,
        )
        if grant_binding_key:
            lookup = lookup.where(SpaceChannelMember.grant_binding_key == grant_binding_key)
        else:
            lookup = lookup.where(
                SpaceChannelMember.grant_subject_type == grant_subject_type,
                SpaceChannelMember.grant_subject_id == grant_subject_id,
                SpaceChannelMember.grant_relation == grant_relation,
                SpaceChannelMember.grant_include_children == grant_include_children,
            )
        existing = (await self.session.exec(lookup)).first()
        if existing:
            existing.user_role = legacy_role_for_channel_relation(relation)
            existing.status = status
            existing.relation = relation
            existing.grant_subject_type = grant_subject_type
            existing.grant_subject_id = grant_subject_id
            existing.grant_relation = grant_relation
            existing.grant_include_children = grant_include_children
            existing.grant_model_id = grant_model_id
            existing.grant_binding_key = grant_binding_key
            return await self.update(existing)

        return await self.add_member(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=user_id,
            role=legacy_role_for_channel_relation(relation),
            status=status,
            relation=relation,
            grant_subject_type=grant_subject_type,
            grant_subject_id=grant_subject_id,
            grant_relation=grant_relation,
            grant_include_children=grant_include_children,
            grant_model_id=grant_model_id,
            grant_binding_key=grant_binding_key,
        )

    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str) -> int:
        query = (
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.grant_binding_key == grant_binding_key,
            )
        )
        result = await self.session.exec(query)
        await self.session.commit()
        return result.rowcount or 0

    async def delete_channel_membership_source_users_not_in(
        self,
        channel_id: str,
        grant_binding_key: str,
        user_ids: list[int],
    ) -> int:
        query = (
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.grant_binding_key == grant_binding_key,
            )
        )
        if user_ids:
            query = query.where(~col(SpaceChannelMember.user_id).in_(user_ids))
        result = await self.session.exec(query)
        await self.session.commit()
        return result.rowcount or 0

    async def has_channel_organization_source(self, channel_id: str, user_id: int) -> bool:
        query = select(func.count()).select_from(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            col(SpaceChannelMember.grant_subject_type).in_(['department', 'user_group']),
        )
        result = await self.session.exec(query)
        return (result.one() or 0) > 0

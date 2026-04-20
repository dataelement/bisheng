from typing import List, Optional

from sqlalchemy import case, func
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    SpaceChannelMember,
    BusinessTypeEnum,
    UserRoleEnum,
    MembershipStatusEnum,
)
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.user.domain.models.user import User


class SpaceChannelMemberRepositoryImpl(BaseRepositoryImpl[SpaceChannelMember, int], SpaceChannelMemberRepository):
    """SpaceChannelMember repository implementation for managing space and channel memberships."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SpaceChannelMember)

    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        new_member = SpaceChannelMember(
            business_id=business_id,
            business_type=business_type,
            user_id=user_id,
            user_role=role,
            status=status
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
            col(SpaceChannelMember.user_role).in_(roles)
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def find_membership(self, business_id: str, business_type: BusinessTypeEnum,
                              user_id: int) -> Optional[SpaceChannelMember]:
        """Find a specific membership by business ID, type, and user ID."""
        query = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == business_id,
            SpaceChannelMember.business_type == business_type,
            SpaceChannelMember.user_id == user_id
        )
        result = await self.session.exec(query)
        return result.first()

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
            (SpaceChannelMember.user_role == UserRoleEnum.CREATOR, 0),
            (SpaceChannelMember.user_role == UserRoleEnum.ADMIN, 1),
            else_=2
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
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.exec(query)
        return list(result.all())

    async def count_channel_members(self, channel_id: str,
                                    user_ids: Optional[List[int]] = None) -> int:
        """Count the total number of channel members, optionally filtered by user IDs."""
        query = select(func.count()).select_from(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )

        if user_ids is not None:
            query = query.where(col(SpaceChannelMember.user_id).in_(user_ids))

        result = await self.session.exec(query)
        return result.one()

    async def find_members_by_role(self, channel_id: str, role: UserRoleEnum) -> List[SpaceChannelMember]:
        """按角色查询频道成员"""
        query = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == channel_id,
            SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            SpaceChannelMember.user_role == role,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def remove_non_creator_members(self, channel_id: str) -> None:
        """Remove all members from a channel except the creator (hard delete)."""
        from sqlmodel import delete
        query = (
            delete(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_id == channel_id,
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.user_role != UserRoleEnum.CREATOR
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

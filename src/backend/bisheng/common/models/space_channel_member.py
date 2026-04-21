from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List

from sqlalchemy import Column, CHAR, Enum as SQLEnum, DateTime, String, text, Boolean, delete, func, case
from sqlmodel import Field, select, update, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.user.domain.models.user import User


class BusinessTypeEnum(str, Enum):
    SPACE = 'space'
    CHANNEL = 'channel'


class UserRoleEnum(str, Enum):
    CREATOR = 'creator'
    ADMIN = 'admin'
    MEMBER = 'member'


class MembershipStatusEnum(str, Enum):
    ACTIVE = 'ACTIVE'
    PENDING = 'PENDING'
    REJECTED = 'REJECTED'


REJECTED_STATUS_DISPLAY_WINDOW = timedelta(hours=24)


class SpaceChannelMember(SQLModelSerializable, table=True):
    __tablename__ = 'space_channel_member'
    id: Optional[int] = Field(default=None, primary_key=True)

    business_id: str = Field(..., description='Business ID', sa_column=Column(CHAR(36), nullable=False, index=True))
    business_type: BusinessTypeEnum = Field(...,
                                            sa_column=Column(SQLEnum(BusinessTypeEnum), nullable=False, index=True))
    user_id: int = Field(..., description='User ID', nullable=False)
    user_role: UserRoleEnum = Field(..., description='User Role',
                                    sa_column=Column(SQLEnum(UserRoleEnum), nullable=False))
    status: MembershipStatusEnum = Field(
        default=MembershipStatusEnum.ACTIVE,
        description='Membership Status',
        sa_column=Column(
            SQLEnum(MembershipStatusEnum, name='space_channel_member_status_enum'),
            nullable=False,
            server_default=text("'ACTIVE'"),
        ),
    )
    membership_source: str = Field(
        default='manual',
        description='manual | department_admin',
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=text("'manual'"),
        ),
    )
    is_pinned: bool = Field(default=False, description='Whether the channel is pinned to top',
                            sa_column=Column(Boolean, nullable=False, server_default=text('0')))

    create_time: datetime = Field(default_factory=datetime.now, description='Creation Time',
                                  sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))

    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=True, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatusEnum.ACTIVE

    @property
    def is_pending(self) -> bool:
        return self.status == MembershipStatusEnum.PENDING

    @property
    def is_rejected(self) -> bool:
        return self.status == MembershipStatusEnum.REJECTED

    def is_recently_rejected(self, now: Optional[datetime] = None) -> bool:
        if not self.is_rejected or self.update_time is None:
            return False

        reference_time = now or datetime.now()
        return self.update_time >= reference_time - REJECTED_STATUS_DISPLAY_WINDOW


class SpaceChannelMemberDao:
    """ DAO for all DB access on space_channel_member table """

    @classmethod
    async def update(cls, member: SpaceChannelMember) -> SpaceChannelMember:
        """ Async: Update an existing member record """
        if member.id is None:
            raise ValueError('Member ID is required')

        async with get_async_db_session() as session:
            session.add(member)
            await session.commit()
            await session.refresh(member)
            return member

    @classmethod
    async def async_insert_member(cls, member: SpaceChannelMember) -> SpaceChannelMember:
        """ Async: Insert a new member record """

        async with get_async_db_session() as session:
            session.add(member)
            await session.commit()
            await session.refresh(member)
            return member

    @classmethod
    async def async_find_member(cls, space_id: int, user_id: int) -> Optional[SpaceChannelMember]:
        """ Async: Find an existing membership record for a user in a space (regardless of status) """

        statement = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def find_space_members_paginated(
            cls, space_id: int, user_ids: Optional[List[int]] = None, page: int = 1, page_size: int = 20
    ) -> List[SpaceChannelMember]:
        """ Async: Paginate active members for a space, creators and admins first """
        role_order = case(
            (SpaceChannelMember.user_role == UserRoleEnum.CREATOR, 0),
            (SpaceChannelMember.user_role == UserRoleEnum.ADMIN, 1),
            else_=2
        )

        query = select(SpaceChannelMember).join(
            User, SpaceChannelMember.user_id == User.user_id
        ).where(
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )

        if user_ids is not None:
            query = query.where(col(SpaceChannelMember.user_id).in_(user_ids))

        # Order by role (creator > admin > member) then by username alphabetically
        query = query.order_by(role_order, User.user_name.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        async with get_async_db_session() as session:
            result = await session.exec(query)
            return result.all()

    @classmethod
    async def count_space_members_with_keyword(
            cls, space_id: int, user_ids: Optional[List[int]] = None
    ) -> int:
        """ Async: Count active members for a space, filtered by user_ids, for pagination """
        from sqlalchemy import func
        statement = select(func.count()).where(
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
        )
        if user_ids is not None:
            if not user_ids:
                return 0
            statement = statement.where(SpaceChannelMember.user_id.in_(user_ids))

        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def async_get_active_member_role(cls, space_id: int, user_id: int) -> Optional[UserRoleEnum]:
        """ Async: Return the role of an ACTIVE member, or None if not an active member """

        statement = select(SpaceChannelMember.user_role).where(
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def async_count_user_space_subscriptions(cls, user_id: int) -> int:
        """ Async: Count how many spaces the user has actively subscribed to (non-creator) """

        from sqlmodel import func
        statement = select(func.count()).where(
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.user_role != UserRoleEnum.CREATOR,
            SpaceChannelMember.status.in_([
                MembershipStatusEnum.ACTIVE,
                MembershipStatusEnum.PENDING,
            ]),
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def async_count_space_members(cls, space_id: int) -> int:
        """ Async: Count how many spaces the user has active (non-creator) """
        statement = select(func.count()).where(
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
        )
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def async_count_members_batch(cls, space_ids: List[str]) -> dict:
        """Async: Batch count active (non-creator) members for multiple spaces.

        Returns a dict mapping space_id (str) -> subscriber count.
        """
        if not space_ids:
            return {}
        statement = (
            select(SpaceChannelMember.business_id, func.count().label('cnt'))
            .where(
                SpaceChannelMember.business_id.in_(space_ids),
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            )
            .group_by(SpaceChannelMember.business_id)
        )
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return {row[0]: row[1] for row in rows}

    @classmethod
    async def async_get_members_by_space(cls, space_id: int, order_by: str = 'user_id',
                                         user_roles: List[UserRoleEnum] = None,
                                         status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE) -> List[
        SpaceChannelMember]:
        """ Async: Get all active members of a space """

        statement = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id == str(space_id),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.status == status
        )

        if user_roles:
            statement = statement.where(SpaceChannelMember.user_role.in_(user_roles))
        if order_by == 'user_id':
            statement = statement.order_by(SpaceChannelMember.user_id.asc())
        elif order_by == 'create_time':
            statement = statement.order_by(SpaceChannelMember.create_time.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_user_followed_space_ids(cls, user_id: int) -> List[str]:
        """ Async: Get list of space_ids the user follows (not as creator) """

        statement = select(SpaceChannelMember.business_id).where(
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            SpaceChannelMember.user_role != UserRoleEnum.CREATOR
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_user_followed_members(cls, user_id: int) -> List[SpaceChannelMember]:
        """
        Async: Get all active followed space membership records for a user (non-creator),
        ordered by is_pinned DESC then create_time DESC so pinned spaces appear first.
        """

        statement = (
            select(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.user_id == user_id,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.user_role != UserRoleEnum.CREATOR,
            )
            .order_by(
                SpaceChannelMember.is_pinned.desc(),
                SpaceChannelMember.create_time.desc(),
            )
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_user_created_members(cls, user_id: int) -> List[SpaceChannelMember]:
        """
        Async: Get all active created space membership records for a user
        (creator only), ordered by is_pinned DESC then create_time DESC.
        """

        statement = (
            select(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.user_id == user_id,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.user_role == UserRoleEnum.CREATOR,
            )
            .order_by(
                SpaceChannelMember.is_pinned.desc(),
                SpaceChannelMember.create_time.desc(),
            )
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_user_space_members(cls, user_id: int) -> List[SpaceChannelMember]:
        """Async: Get all active space membership rows for a user."""

        statement = (
            select(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.user_id == user_id,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            )
            .order_by(
                SpaceChannelMember.is_pinned.desc(),
                SpaceChannelMember.create_time.desc(),
            )
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_user_managed_members(cls, user_id: int) -> List[SpaceChannelMember]:
        """
        Async: Get all active managed space membership records for a user
        (admin and creator), ordered by is_pinned DESC then create_time DESC.
        """

        statement = (
            select(SpaceChannelMember)
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                SpaceChannelMember.user_id == user_id,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                SpaceChannelMember.user_role.in_([UserRoleEnum.ADMIN, UserRoleEnum.CREATOR]),
            )
            .order_by(
                SpaceChannelMember.is_pinned.desc(),
                SpaceChannelMember.create_time.desc(),
            )
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_followed_members_for_spaces(cls, user_id: int, space_ids: List[str]) -> List[
        SpaceChannelMember]:
        """ Async: Get ACTIVE follow-status members for a batch of space IDs and a given user """

        if not space_ids:
            return []
        statement = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id.in_(space_ids),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
            SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
            SpaceChannelMember.user_role != UserRoleEnum.CREATOR
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_get_all_members_for_spaces(cls, user_id: int, space_ids: List[str]) -> List[SpaceChannelMember]:
        """
        Async: Get ALL membership records (active AND pending) for a user across a batch of spaces.
        Used by the Knowledge Square to detect whether a user has already joined or applied.
        """

        if not space_ids:
            return []
        statement = select(SpaceChannelMember).where(
            SpaceChannelMember.business_id.in_(space_ids),
            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            SpaceChannelMember.user_id == user_id,
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def async_delete_non_creator_members(cls, space_id: int):
        """ Async: Remove all non-creator members from a space """

        async with get_async_db_session() as session:
            await session.exec(
                delete(SpaceChannelMember).where(
                    SpaceChannelMember.business_id == str(space_id),
                    SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                    SpaceChannelMember.user_role != UserRoleEnum.CREATOR
                )
            )
            await session.commit()

    @classmethod
    async def async_delete_rejected_members(cls, space_id: int):
        """Async: Remove all rejected members from a space."""

        async with get_async_db_session() as session:
            await session.exec(
                delete(SpaceChannelMember).where(
                    SpaceChannelMember.business_id == str(space_id),
                    SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                    SpaceChannelMember.status == MembershipStatusEnum.REJECTED,
                )
            )
            await session.commit()

    @classmethod
    async def pin_space_id(cls, space_id: int, user_id=int, is_pinned: bool = True) -> bool:
        statement = update(SpaceChannelMember).where(
            col(SpaceChannelMember.business_id) == str(space_id),
            col(SpaceChannelMember.business_type) == BusinessTypeEnum.SPACE,
            col(SpaceChannelMember.user_id) == user_id,
            col(SpaceChannelMember.status) == MembershipStatusEnum.ACTIVE).values(is_pinned=is_pinned)
        async with get_async_db_session() as session:
            await session.execute(statement)
            await session.commit()
            return True

    @classmethod
    async def delete_space_member(cls, space_id: int, user_id) -> bool:
        statement = delete(SpaceChannelMember).where(
            col(SpaceChannelMember.business_id) == str(space_id),
            col(SpaceChannelMember.business_type) == BusinessTypeEnum.SPACE,
            col(SpaceChannelMember.user_id) == user_id
        )
        async with get_async_db_session() as session:
            await session.execute(statement)
            await session.commit()
            return True

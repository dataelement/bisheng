from datetime import datetime
from typing import List, Optional, Tuple, Any

from sqlalchemy import case, func, or_
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.common.models.space_channel_member import (
    SpaceChannelMember,
    BusinessTypeEnum,
    MembershipStatusEnum,
    REJECTED_STATUS_DISPLAY_WINDOW,
)
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class ChannelRepositoryImpl(BaseRepositoryImpl[Channel, str], ChannelRepository):
    """Channel repository implementation"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Channel)

    async def find_channels_by_ids(self, channel_ids: List[str]) -> List[Channel]:
        """Find channels by a list of channel IDs."""
        if not channel_ids:
            return []
        query = select(Channel).where(col(Channel.id).in_(channel_ids))
        result = await self.session.exec(query)
        return list(result.all())

    async def find_square_channels(self, user_id: int, keyword: Optional[str] = None,
                                   page: int = 1, page_size: int = 20) -> List[Tuple[Any, ...]]:
        """
        Find released channels for the channel square with subscription status and subscriber count.
        Uses multi-table LEFT JOIN:
        - LEFT JOIN space_channel_member for current user's subscription status
        - LEFT JOIN subquery for subscriber count (status=ACTIVE)
        Returns list of tuples:
        (Channel, user_subscription_status, user_subscription_update_time, subscriber_count)
        """
        rejection_cutoff = datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW

        # Subquery: count subscribers (status=ACTIVE) per channel
        subscriber_subq = (
            select(
                SpaceChannelMember.business_id,
                func.count().label('subscriber_count')
            )
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.status == MembershipStatusEnum.ACTIVE
            )
            .group_by(SpaceChannelMember.business_id)
            .subquery()
        )

        # Main query with LEFT JOINs
        query = (
            select(
                Channel,
                SpaceChannelMember.status.label('user_subscription_status'),
                SpaceChannelMember.update_time.label('user_subscription_update_time'),
                func.coalesce(subscriber_subq.c.subscriber_count, 0).label('subscriber_count')
            )
            .outerjoin(
                SpaceChannelMember,
                (SpaceChannelMember.business_id == Channel.id) &
                (SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL) &
                (SpaceChannelMember.user_id == user_id)
            )
            .outerjoin(
                subscriber_subq,
                subscriber_subq.c.business_id == Channel.id
            )
            .where(
                Channel.is_released == True,
                Channel.visibility != ChannelVisibilityEnum.PRIVATE
            )
        )

        # Apply keyword filter (fuzzy search on name and description)
        if keyword:
            like_pattern = f'%{keyword}%'
            query = query.where(
                or_(
                    Channel.name.like(like_pattern),
                    Channel.description.like(like_pattern)
                )
            )

        subscription_order = case(
            (SpaceChannelMember.status.is_(None), 0),
            (
                (SpaceChannelMember.status == MembershipStatusEnum.REJECTED)
                & (SpaceChannelMember.update_time < rejection_cutoff),
                0,
            ),
            else_=1
        )
        query = query.order_by(
            subscription_order.asc(),
            func.coalesce(Channel.update_time, Channel.create_time).desc()
        )

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.session.exec(query)
        return list(result.all())

    async def count_square_channels(self, keyword: Optional[str] = None) -> int:
        """Count total released channels matching the keyword filter."""
        query = (
            select(func.count())
            .select_from(Channel)
            .where(
                Channel.is_released == True,
                Channel.visibility != ChannelVisibilityEnum.PRIVATE
            )
        )

        if keyword:
            like_pattern = f'%{keyword}%'
            query = query.where(
                or_(
                    Channel.name.like(like_pattern),
                    Channel.description.like(like_pattern)
                )
            )

        result = await self.session.exec(query)
        return result.one()

    async def find_channels_by_source_id(self, source_id: str) -> List[Channel]:
        """Find channels whose source_list contains the specified source_id."""
        if not source_id:
            return []
        # Use json_contains to check if source_list (JSON array) contains the source_id
        query = select(Channel).where(func.json_contains(Channel.source_list, f'"{source_id}"'))
        result = await self.session.exec(query)
        return list(result.all())

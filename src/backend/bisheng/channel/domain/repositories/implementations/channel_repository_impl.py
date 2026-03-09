from typing import List, Optional, Tuple, Any

from sqlalchemy import case, func, or_
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.common.models.space_channel_member import SpaceChannelMember, BusinessTypeEnum
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
        - LEFT JOIN subquery for subscriber count (status=True)
        Returns list of tuples: (Channel, user_subscription_status, subscriber_count)
        """
        # Subquery: count subscribers (status=True) per channel
        subscriber_subq = (
            select(
                SpaceChannelMember.business_id,
                func.count().label('subscriber_count')
            )
            .where(
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.status == True
            )
            .group_by(SpaceChannelMember.business_id)
            .subquery()
        )

        # Main query with LEFT JOINs
        query = (
            select(
                Channel,
                SpaceChannelMember.status.label('user_subscription_status'),
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
            .where(Channel.is_released == True)
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

        # Sorting: unsubscribed/unapplied first (status IS NULL → 0), subscribed/applied last (→ 1)
        # Within same group, sort by update_time desc (fallback to create_time if NULL)
        subscription_order = case(
            (SpaceChannelMember.status.is_(None), 0),
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
            .where(Channel.is_released == True)
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


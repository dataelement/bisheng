from typing import List

from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
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

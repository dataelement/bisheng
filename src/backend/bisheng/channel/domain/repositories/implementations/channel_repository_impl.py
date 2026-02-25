from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl

class ChannelRepositoryImpl(BaseRepositoryImpl[Channel, str], ChannelRepository):
    """Shared link repository implementation"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Channel)

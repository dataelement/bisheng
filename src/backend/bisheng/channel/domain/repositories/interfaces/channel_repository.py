from abc import ABC, abstractmethod
from typing import List

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelRepository(BaseRepository[Channel, str], ABC):
    """Channel Repository Interface"""

    @abstractmethod
    async def find_channels_by_ids(self, channel_ids: List[str]) -> List[Channel]:
        """Find channels by a list of channel IDs."""
        pass

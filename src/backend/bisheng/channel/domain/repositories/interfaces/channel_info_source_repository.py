from abc import ABC, abstractmethod
from typing import List

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelInfoSourceRepository(BaseRepository[ChannelInfoSource, str], ABC):
    @abstractmethod
    async def find_by_ids(self, source_ids: List[str]) -> List[ChannelInfoSource]:
        """Find channel information sources by their IDs."""
        pass

    @abstractmethod
    async def batch_add(self, sources: List[ChannelInfoSource]) -> None:
        """Batch add channel information sources."""
        pass

    @abstractmethod
    def get_by_page(self, page: int = 1, page_size: int = 20) -> List[ChannelInfoSource]:
        """Get all channel information sources by page."""
        pass

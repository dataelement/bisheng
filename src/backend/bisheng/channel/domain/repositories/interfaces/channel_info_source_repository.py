from abc import ABC, abstractmethod
from typing import List

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource


class ChannelInfoSourceRepository(ABC):
    @abstractmethod
    async def find_by_ids(self, source_ids: List[str]) -> List[ChannelInfoSource]:
        """Find channel information sources by their IDs."""
        pass

    @abstractmethod
    async def batch_add(self, sources: List[ChannelInfoSource]) -> None:
        """Batch add channel information sources."""
        pass

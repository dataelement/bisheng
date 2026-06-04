from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Any

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelRepository(BaseRepository[Channel, str], ABC):
    """Channel Repository Interface"""

    @abstractmethod
    async def find_channels_by_ids(self, channel_ids: List[str]) -> List[Channel]:
        """Find channels by a list of channel IDs."""
        pass

    @abstractmethod
    async def find_square_channels(self, user_id: int, keyword: Optional[str] = None,
                                   page: int = 1, page_size: int = 20) -> List[Tuple[Any, ...]]:
        """
        Find released channels for the channel square with subscription status and subscriber count.
        Returns a list of tuples:
        (Channel, user_subscription_status, user_subscription_update_time, subscriber_count)
        """
        pass

    @abstractmethod
    async def count_square_channels(self, keyword: Optional[str] = None) -> int:
        """Count total released channels matching the keyword filter."""
        pass

    @abstractmethod
    async def find_all_referenced_source_ids(self) -> set[str]:
        """Return the union of all source_ids referenced by any channel in the current tenant.

        This is the desired-subscription set used by the daily reconcile. It reads the
        source_list JSON column of every channel and unions the ids in Python — no
        JSON_CONTAINS / JSON_EXTRACT, so it stays DM8-compatible.
        """
        pass

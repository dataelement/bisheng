from abc import ABC, abstractmethod
from typing import Any

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelRepository(BaseRepository[Channel, str], ABC):
    """Channel Repository Interface"""

    @abstractmethod
    async def find_channels_by_ids(self, channel_ids: list[str]) -> list[Channel]:
        """Find channels by a list of channel IDs."""
        pass

    @abstractmethod
    async def find_channels_by_user_id(self, user_id: int) -> list[Channel]:
        """Find all channels created by the given user (tenant auto-scoped)."""
        pass

    @abstractmethod
    async def find_by_creation_request(
        self,
        *,
        tenant_id: int,
        user_id: int,
        creation_request_id: str,
    ) -> Channel | None:
        """Find the durable result of one creator-scoped creation command."""
        pass

    @abstractmethod
    async def save_creation(self, channel: Channel) -> tuple[Channel, bool]:
        """Insert a creation command or recover its concurrent winner."""
        pass

    @abstractmethod
    async def find_followed_by_visible_ids(
        self,
        channel_ids: list[str],
        *,
        tenant_id: int,
        exclude_creator_id: int,
    ) -> list[Channel]:
        """Load the "followed" subset of a bounded visible-id chunk.

        Given the OpenFGA-resolved visible channel ids for the current user, load
        the concrete ``channel`` rows in one indexed ``IN`` query, scoped to the
        current tenant and excluding the caller's own created channels (they
        belong to the "created" list, not the "followed" list). Mirrors the
        knowledge-space equivalent ``async_get_joined_spaces_by_visible_ids`` so
        the "我加入的" pattern stays uniform across resources.
        """
        pass

    @abstractmethod
    async def find_square_channels(
        self,
        user_id: int,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[tuple[Any, ...]]:
        """
        Find released channels for the channel square with subscription status and subscriber count.
        Returns a list of tuples:
        (Channel, user_subscription_status, user_subscription_update_time, subscriber_count)
        """
        pass

    @abstractmethod
    async def find_public_recommend_channels(
        self,
        user_id: int,
        candidate_limit: int = 100,
    ) -> list[tuple[Any, ...]]:
        """
        Find released PUBLIC channels for the home-page discovery carousel.
        Same tuple shape as find_square_channels, restricted to visibility=PUBLIC and
        capped at candidate_limit (unpaginated). Caller re-sorts by ES article count.
        """
        pass

    @abstractmethod
    async def count_square_channels(self, keyword: str | None = None) -> int:
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

    @abstractmethod
    async def find_channels_referencing_source(self, source_id: str) -> list[Channel]:
        """Return current-tenant channels referencing the source."""
        pass

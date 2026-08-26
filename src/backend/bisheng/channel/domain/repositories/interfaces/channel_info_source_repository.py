from abc import ABC, abstractmethod

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelInfoSourceRepository(BaseRepository[ChannelInfoSource, str], ABC):
    @abstractmethod
    async def find_by_ids(self, source_ids: list[str]) -> list[ChannelInfoSource]:
        """Find channel information sources by their IDs."""
        pass

    @abstractmethod
    async def batch_add(self, sources: list[ChannelInfoSource]) -> None:
        """Batch add channel information sources."""
        pass

    @abstractmethod
    async def upsert_metadata(self, sources: list[ChannelInfoSource]) -> None:
        """Idempotently insert or update public source metadata."""
        pass

    @abstractmethod
    def get_by_page(
        self,
        information_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[ChannelInfoSource]:
        """Get all channel information sources by page."""
        pass

    @abstractmethod
    async def find_all(self) -> list[ChannelInfoSource]:
        """Return all public channel information source rows."""
        pass

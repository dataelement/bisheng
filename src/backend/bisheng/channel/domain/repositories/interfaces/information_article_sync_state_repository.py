from abc import ABC, abstractmethod

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource


class InformationArticleSyncStateRepository(ABC):
    @abstractmethod
    async def find_by_source_id(self, source_id: str) -> ChannelInfoSource | None:
        """Return the current public progress row."""

    @abstractmethod
    async def commit_if_unchanged(
        self,
        source_id: str,
        expected_state: ChannelInfoSource,
        next_cursor: int | None,
        remote_sync_at: int | None,
        article_list_updated_at: int | None,
    ) -> bool:
        """Commit progress only when the persisted values still match the snapshot."""

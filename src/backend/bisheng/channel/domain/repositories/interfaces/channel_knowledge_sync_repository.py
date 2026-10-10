from abc import ABC, abstractmethod

from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync


class ChannelKnowledgeSyncRepository(ABC):
    @abstractmethod
    async def find_enabled_by_channel_ids(self, channel_ids: list[str]) -> list[ChannelKnowledgeSync]:
        """Return enabled configs for current-tenant verified channel IDs."""

    @abstractmethod
    async def find_by_id(self, sync_config_id: str) -> ChannelKnowledgeSync | None:
        """Return a config; callers must separately verify its channel tenant."""

from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelKnowledgeSyncRepository(BaseRepository[ChannelKnowledgeSync, str], ABC):
    @abstractmethod
    async def touch_update_time(self, sync_id: str, now: datetime) -> None:
        """记录成功同步时间。"""

from datetime import datetime

from sqlalchemy import update
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.interfaces.channel_knowledge_sync_repository import (
    ChannelKnowledgeSyncRepository,
)
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class ChannelKnowledgeSyncRepositoryImpl(BaseRepositoryImpl[ChannelKnowledgeSync, str], ChannelKnowledgeSyncRepository):
    def __init__(self, session):
        super().__init__(session, ChannelKnowledgeSync)

    async def touch_update_time(self, sync_id: str, now: datetime) -> None:
        await self.session.execute(
            update(ChannelKnowledgeSync)
            .where(
                ChannelKnowledgeSync.id == sync_id,
            )
            .values(update_time=now)
        )

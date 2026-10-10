from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.interfaces.channel_knowledge_sync_repository import (
    ChannelKnowledgeSyncRepository,
)


class ChannelKnowledgeSyncRepositoryImpl(ChannelKnowledgeSyncRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_enabled_by_channel_ids(self, channel_ids: list[str]) -> list[ChannelKnowledgeSync]:
        if not channel_ids:
            return []
        statement = select(ChannelKnowledgeSync).where(
            col(ChannelKnowledgeSync.channel_id).in_(channel_ids),
            ChannelKnowledgeSync.is_enabled == True,  # noqa: E712 - DM8 rejects IS 1
        )
        return list((await self.session.exec(statement)).all())

    async def find_by_id(self, sync_config_id: str) -> ChannelKnowledgeSync | None:
        return await self.session.get(ChannelKnowledgeSync, sync_config_id)

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import ChannelInfoSourceRepository


class ChannelInfoSourceRepositoryImpl(ChannelInfoSourceRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_ids(self, source_ids: List[str]) -> List[ChannelInfoSource]:
        if not source_ids:
            return []
        statement = select(ChannelInfoSource).where(ChannelInfoSource.id.in_(source_ids))
        result = await self.session.exec(statement)
        return list(result.all())

    async def batch_add(self, sources: List[ChannelInfoSource]) -> None:
        if not sources:
            return
        self.session.add_all(sources)
        await self.session.commit()

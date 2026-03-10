from typing import List, Union

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col, Session

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import ChannelInfoSourceRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class ChannelInfoSourceRepositoryImpl(BaseRepositoryImpl[ChannelInfoSource, str], ChannelInfoSourceRepository):
    def __init__(self, session: Union[AsyncSession, Session]):
        super().__init__(session, ChannelInfoSource)
        self.session = session

    async def find_by_ids(self, source_ids: List[str]) -> List[ChannelInfoSource]:
        if not source_ids:
            return []
        statement = select(ChannelInfoSource).where(col(ChannelInfoSource.id).in_(source_ids))
        result = await self.session.exec(statement)
        return list(result.all())

    async def batch_add(self, sources: List[ChannelInfoSource]) -> None:
        if not sources:
            return
        self.session.add_all(sources)
        await self.session.commit()

    def get_by_page(self, page: int = 1, page_size: int = 20) -> List[ChannelInfoSource]:
        offset = (page - 1) * page_size
        statement = select(ChannelInfoSource).offset(offset).limit(page_size).order_by(ChannelInfoSource.create_time)
        result = self.session.exec(statement)
        return list(result.all())

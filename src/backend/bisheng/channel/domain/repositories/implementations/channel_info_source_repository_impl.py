from typing import List, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col, delete, Session

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
        try:
            self.session.add_all(sources)
            await self.session.commit()
        except IntegrityError:
            # Concurrent insert of the same source id — e.g. two channels created at
            # almost the same time both selecting the same brand-new source. Roll back,
            # drop the ids that now already exist, and retry with only the new ones so
            # the insert is effectively idempotent instead of failing the caller.
            await self.session.rollback()
            existing = await self.find_by_ids([source.id for source in sources])
            existing_ids = {row.id for row in existing}
            remaining = [source for source in sources if source.id not in existing_ids]
            if remaining:
                self.session.add_all(remaining)
                await self.session.commit()

    def get_by_page(self, information_id: str = None, page: int = 1, page_size: int = 20) -> List[ChannelInfoSource]:
        offset = (page - 1) * page_size
        statement = select(ChannelInfoSource)
        if information_id:
            statement = statement.where(ChannelInfoSource.id == information_id)
        statement = statement.offset(offset).limit(page_size).order_by(ChannelInfoSource.create_time)
        result = self.session.exec(statement)
        return list(result.all())

    async def find_all(self) -> List[ChannelInfoSource]:
        statement = select(ChannelInfoSource)
        result = await self.session.exec(statement)
        return list(result.all())

    async def delete_by_ids(self, source_ids: List[str]) -> None:
        if not source_ids:
            return
        statement = delete(ChannelInfoSource).where(col(ChannelInfoSource.id).in_(source_ids))
        await self.session.exec(statement)
        await self.session.commit()

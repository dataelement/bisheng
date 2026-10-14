from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.interfaces.information_article_sync_state_repository import (
    InformationArticleSyncStateRepository,
)


class InformationArticleSyncStateRepositoryImpl(InformationArticleSyncStateRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_source_id(self, source_id: str) -> ChannelInfoSource | None:
        return await self.session.get(ChannelInfoSource, source_id)

    async def commit_if_unchanged(
        self,
        source_id: str,
        expected_state: ChannelInfoSource,
        next_cursor: int | None,
        remote_sync_at: int | None,
        article_list_updated_at: int | None,
    ) -> bool:
        expected = (
            expected_state.article_cursor_create_time,
            expected_state.processed_remote_sync_at,
            expected_state.processed_article_list_updated_at,
        )
        statement = (
            select(ChannelInfoSource)
            .where(ChannelInfoSource.id == source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = (await self.session.exec(statement)).first()
        if current is None:
            await self.session.rollback()
            return False
        actual = (
            current.article_cursor_create_time,
            current.processed_remote_sync_at,
            current.processed_article_list_updated_at,
        )
        if actual != expected:
            await self.session.rollback()
            return False
        current.article_cursor_create_time = next_cursor
        current.processed_remote_sync_at = remote_sync_at
        current.processed_article_list_updated_at = article_list_updated_at
        self.session.add(current)
        await self.session.commit()
        return True

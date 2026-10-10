from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.information_article_sync_state import InformationArticleSyncState
from bisheng.channel.domain.repositories.interfaces.information_article_sync_state_repository import (
    InformationArticleSyncStateRepository,
)


class InformationArticleSyncStateRepositoryImpl(InformationArticleSyncStateRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_source_id(self, source_id: str) -> InformationArticleSyncState | None:
        return await self.session.get(InformationArticleSyncState, source_id)

    async def create_initial_boundary_if_absent(
        self, source_id: str, cursor: int | None
    ) -> InformationArticleSyncState:
        existing = await self.find_by_source_id(source_id)
        if existing is not None:
            return await self._fill_empty_boundary(existing, cursor)
        row = InformationArticleSyncState(source_id=source_id, article_cursor_create_time=cursor)
        self.session.add(row)
        try:
            await self.session.commit()
            await self.session.refresh(row)
            return row
        except IntegrityError:
            await self.session.rollback()
            winner = await self.find_by_source_id(source_id)
            if winner is None:
                raise
            return await self._fill_empty_boundary(winner, cursor)

    async def _fill_empty_boundary(
        self,
        existing: InformationArticleSyncState,
        cursor: int | None,
    ) -> InformationArticleSyncState:
        if existing.article_cursor_create_time is not None or cursor is None:
            return existing
        statement = (
            select(InformationArticleSyncState)
            .where(InformationArticleSyncState.source_id == existing.source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = (await self.session.exec(statement)).first()
        if current is None:
            await self.session.rollback()
            raise RuntimeError("information article sync state disappeared")
        if current.article_cursor_create_time is None:
            current.article_cursor_create_time = cursor
            self.session.add(current)
            await self.session.commit()
        return current

    async def commit_if_unchanged(
        self,
        source_id: str,
        expected_state: InformationArticleSyncState,
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
            select(InformationArticleSyncState)
            .where(InformationArticleSyncState.source_id == source_id)
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

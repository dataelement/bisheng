from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)


async def test_migration_tracks_only_new_target_entry_current_state():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
        await connection.run_sync(KnowledgeFile.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        track_fulltext_file_changes(session)
        session.add(KnowledgeFile(id=81, tenant_id=1, knowledge_id=20, file_name="migrated.pdf", status=2))
        await commit_tracked_fulltext_changes(
            session,
            trigger_type="migration_committed",
            multi_tenant_enabled=False,
        )

        row = (await session.exec(select(KnowledgeFulltextOutbox))).one()
        assert (row.aggregate_id, row.knowledge_id, row.desired_action) == (81, 20, "sync_current")
    finally:
        await session.close()
        await engine.dispose()

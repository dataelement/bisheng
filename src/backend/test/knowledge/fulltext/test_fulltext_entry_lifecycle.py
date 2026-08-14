from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
)
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)


async def test_distribution_entry_ready_then_invalid_advances_same_file_revision():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
        await connection.run_sync(KnowledgeFile.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        track_fulltext_file_changes(session)
        entry = KnowledgeFile(
            id=61,
            tenant_id=1,
            knowledge_id=9,
            file_name="publish.pdf",
            status=2,
            reference_document_id=71,
            entry_type=KnowledgeFileEntryType.PUBLISH.value,
            entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
            projection_status=KnowledgeFileProjectionStatus.READY.value,
        )
        session.add(entry)
        await commit_tracked_fulltext_changes(
            session,
            trigger_type="projection_ready",
            multi_tenant_enabled=False,
        )
        entry.entry_status = KnowledgeFileEntryStatus.INVALID.value
        session.add(entry)
        await commit_tracked_fulltext_changes(
            session,
            trigger_type="distribution_invalidated",
            multi_tenant_enabled=False,
        )

        row = (await session.exec(select(KnowledgeFulltextOutbox))).one()
        assert (row.aggregate_id, row.desired_revision) == (61, 2)
    finally:
        await session.close()
        await engine.dispose()

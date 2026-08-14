from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    request_knowledge_intent,
    track_fulltext_file_changes,
)


async def test_file_metadata_and_scope_changes_share_one_business_transaction():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
        await connection.run_sync(KnowledgeFile.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        track_fulltext_file_changes(session)
        session.add_all(
            [
                KnowledgeFile(id=11, tenant_id=1, knowledge_id=9, file_name="a.pdf", status=2),
                KnowledgeFile(id=12, tenant_id=1, knowledge_id=9, file_name="b.pdf", status=2),
            ]
        )
        await session.flush()
        await request_knowledge_intent(
            session,
            knowledge_id=9,
            tenant_id=1,
            trigger_type="knowledge_metadata_updated",
            multi_tenant_enabled=False,
        )
        await commit_tracked_fulltext_changes(
            session,
            trigger_type="folder_metadata_updated",
            multi_tenant_enabled=False,
        )

        rows = (await session.exec(select(KnowledgeFulltextOutbox))).all()
        assert {(row.aggregate_type, row.aggregate_id) for row in rows} == {
            ("file", 11),
            ("file", 12),
            ("knowledge", 9),
        }
        assert all(row.desired_action in {"sync_current", "fanout_current"} for row in rows)
    finally:
        await session.close()
        await engine.dispose()

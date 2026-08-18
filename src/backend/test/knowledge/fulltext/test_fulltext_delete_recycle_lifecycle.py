from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    KnowledgeFulltextFileRef,
    request_file_delete_intents,
    request_file_sync_intents,
    request_knowledge_intent,
)


async def test_delete_restore_and_scope_delete_coalesce_and_rollback_with_business_state():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    ref = KnowledgeFulltextFileRef(file_id=51, knowledge_id=9)
    try:
        await request_file_delete_intents(
            session,
            [ref],
            trigger_type="recycled",
            multi_tenant_enabled=False,
        )
        await request_file_sync_intents(
            session,
            [ref],
            trigger_type="restored",
            multi_tenant_enabled=False,
        )
        await request_knowledge_intent(
            session,
            knowledge_id=9,
            tenant_id=1,
            trigger_type="space_deleted",
            delete_scope=True,
            multi_tenant_enabled=False,
        )
        rows = (await session.exec(select(KnowledgeFulltextOutbox))).all()
        file_row = next(row for row in rows if row.aggregate_type == "file")
        assert (file_row.desired_revision, file_row.desired_action) == (2, "sync_current")
        assert next(row for row in rows if row.aggregate_type == "knowledge").desired_action == "delete_scope"
        await session.rollback()
        assert (await session.exec(select(KnowledgeFulltextOutbox))).all() == []
    finally:
        await session.close()
        await engine.dispose()

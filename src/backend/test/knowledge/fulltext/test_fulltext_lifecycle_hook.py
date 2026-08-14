from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.services import knowledge_fulltext_after_commit_service as after_commit_service
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    KnowledgeFulltextFileRef,
    commit_tracked_fulltext_changes,
    request_file_delete_intents,
    request_file_sync_intents,
    request_knowledge_intent,
    track_fulltext_file_changes,
)


async def _session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
    return engine, AsyncSession(engine, expire_on_commit=False)


async def test_lifecycle_intents_share_caller_transaction_and_rollback():
    engine, session = await _session()
    try:
        files = [
            KnowledgeFulltextFileRef(file_id=2, knowledge_id=9),
            KnowledgeFulltextFileRef(file_id=1, knowledge_id=9),
            KnowledgeFulltextFileRef(file_id=2, knowledge_id=9),
        ]
        await request_file_sync_intents(
            session,
            files,
            trigger_type="metadata_updated",
            multi_tenant_enabled=False,
        )
        rows = (await session.exec(KnowledgeFulltextOutbox.__table__.select())).all()
        assert len(rows) == 2
        await session.rollback()
        rows = (await session.exec(KnowledgeFulltextOutbox.__table__.select())).all()
        assert rows == []
    finally:
        await session.close()
        await engine.dispose()


async def test_lifecycle_routes_file_delete_and_scope_delete_by_default():
    engine, session = await _session()
    try:
        await request_file_delete_intents(
            session,
            [KnowledgeFulltextFileRef(file_id=1, knowledge_id=9)],
            trigger_type="recycled",
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
        rows = (await session.exec(KnowledgeFulltextOutbox.__table__.select())).all()
        assert len(rows) == 2
        assert {(row.aggregate_type, row.desired_action) for row in rows} == {
            ("file", "delete_current"),
            ("knowledge", "delete_scope"),
        }
    finally:
        await session.close()
        await engine.dispose()


async def test_session_tracker_commits_intent_then_publishes_immediately(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
        await connection.run_sync(KnowledgeFile.__table__.create)
    session = AsyncSession(engine, expire_on_commit=False)
    publisher = MagicMock()
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)
    try:
        track_fulltext_file_changes(session)
        session.add(
            KnowledgeFile(
                id=11,
                tenant_id=1,
                knowledge_id=9,
                file_name="tracked.pdf",
                status=KnowledgeFileStatus.SUCCESS.value,
            )
        )
        await session.flush()
        await commit_tracked_fulltext_changes(
            session,
            trigger_type="projection_ready",
            multi_tenant_enabled=False,
        )

        rows = (await session.exec(KnowledgeFulltextOutbox.__table__.select())).all()
        assert len(rows) == 1
        assert rows[0].aggregate_id == 11
        assert rows[0].desired_action == "sync_current"
        publisher.assert_called_once_with(outbox_id=rows[0].id, revision=1)
    finally:
        await session.close()
        await engine.dispose()

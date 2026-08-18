from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.services import knowledge_fulltext_after_commit_service as after_commit_service


def _row(*, aggregate_id: int = 7, revision: int = 1) -> KnowledgeFulltextOutbox:
    return KnowledgeFulltextOutbox(
        tenant_id=1,
        aggregate_type="file",
        aggregate_id=aggregate_id,
        knowledge_id=9,
        desired_action="sync_current",
        desired_revision=revision,
        trigger_type="test",
    )


def test_sync_session_publishes_latest_revision_only_after_commit(monkeypatch):
    engine = create_engine("sqlite://")
    KnowledgeFulltextOutbox.__table__.create(engine)
    publisher = MagicMock()
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)

    with Session(engine) as session:
        row = _row()
        session.add(row)
        session.flush()
        after_commit_service.track_outbox_after_commit(session, row)
        row.desired_revision = 2
        session.flush()
        after_commit_service.track_outbox_after_commit(session, row)

        publisher.assert_not_called()
        outbox_id = int(row.id)
        session.commit()

    publisher.assert_called_once_with(outbox_id=outbox_id, revision=2)


def test_sync_session_rollback_discards_pending_publish(monkeypatch):
    engine = create_engine("sqlite://")
    KnowledgeFulltextOutbox.__table__.create(engine)
    publisher = MagicMock()
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)

    with Session(engine) as session:
        row = _row()
        session.add(row)
        session.flush()
        after_commit_service.track_outbox_after_commit(session, row)
        session.rollback()

    publisher.assert_not_called()


def test_nested_rollback_discards_only_nested_outbox_ref(monkeypatch):
    engine = create_engine("sqlite://")
    KnowledgeFulltextOutbox.__table__.create(engine)
    publisher = MagicMock()
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)

    with Session(engine) as session:
        outer = _row(aggregate_id=7)
        session.add(outer)
        session.flush()
        after_commit_service.track_outbox_after_commit(session, outer)

        nested = session.begin_nested()
        inner = _row(aggregate_id=8)
        session.add(inner)
        session.flush()
        after_commit_service.track_outbox_after_commit(session, inner)
        nested.rollback()
        outer_id = int(outer.id)
        session.commit()

    publisher.assert_called_once_with(outbox_id=outer_id, revision=1)


async def test_async_session_commit_publishes_and_publisher_failure_is_isolated(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
    publisher = MagicMock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        row = _row()
        session.add(row)
        await session.flush()
        after_commit_service.track_outbox_after_commit(session, row)
        await session.commit()
        saved = await session.get(KnowledgeFulltextOutbox, row.id)

    assert saved is not None
    assert saved.status == "pending"
    publisher.assert_called_once_with(outbox_id=row.id, revision=1)
    await engine.dispose()

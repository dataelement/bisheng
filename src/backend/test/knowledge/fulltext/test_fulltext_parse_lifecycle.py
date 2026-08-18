from contextlib import contextmanager
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlmodel import Session, select

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox
from bisheng.knowledge.domain.services import knowledge_fulltext_after_commit_service as after_commit_service
from bisheng.knowledge.domain.services.knowledge_fulltext_parse_hook import (
    persist_parse_result_with_fulltext_intent,
)


def build_file(status: int) -> KnowledgeFile:
    return KnowledgeFile(
        id=7,
        tenant_id=1,
        user_id=1,
        knowledge_id=9,
        file_name="制度.pdf",
        status=status,
    )


def test_parse_final_status_commits_outbox_then_publishes_immediately(monkeypatch):
    engine = create_engine("sqlite://")
    KnowledgeFile.__table__.create(engine)
    KnowledgeFulltextOutbox.__table__.create(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    file = build_file(KnowledgeFileStatus.SUCCESS.value)
    publisher = MagicMock()
    monkeypatch.setattr(after_commit_service, "_publish_ref", publisher)
    persist_parse_result_with_fulltext_intent(
        file,
        multi_tenant_enabled=False,
        session_factory=session_factory,
    )

    with Session(engine) as session:
        saved_file = session.get(KnowledgeFile, 7)
        outbox = session.exec(select(KnowledgeFulltextOutbox)).one()
        assert saved_file.status == KnowledgeFileStatus.SUCCESS.value
        assert outbox.aggregate_id == 7
        assert outbox.desired_action == "sync_current"
        publisher.assert_called_once_with(outbox_id=outbox.id, revision=1)


def test_reparse_transient_status_does_not_delete_previous_projection():
    engine = create_engine("sqlite://")
    KnowledgeFile.__table__.create(engine)
    KnowledgeFulltextOutbox.__table__.create(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    persist_parse_result_with_fulltext_intent(
        build_file(KnowledgeFileStatus.PROCESSING.value),
        multi_tenant_enabled=False,
        session_factory=session_factory,
    )

    with Session(engine) as session:
        assert session.exec(select(KnowledgeFulltextOutbox)).all() == []


def test_parse_failure_requests_delete_without_changing_failure_status():
    engine = create_engine("sqlite://")
    KnowledgeFile.__table__.create(engine)
    KnowledgeFulltextOutbox.__table__.create(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    persist_parse_result_with_fulltext_intent(
        build_file(KnowledgeFileStatus.FAILED.value),
        multi_tenant_enabled=False,
        session_factory=session_factory,
    )

    with Session(engine) as session:
        saved_file = session.get(KnowledgeFile, 7)
        outbox = session.exec(select(KnowledgeFulltextOutbox)).one()
        assert saved_file.status == KnowledgeFileStatus.FAILED.value
        assert outbox.desired_action == "delete_current"

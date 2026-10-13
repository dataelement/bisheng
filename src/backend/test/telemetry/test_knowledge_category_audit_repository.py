"""使用真实 SQLite 验证分类审计的有界 SELECT 和跨租户隔离。"""

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlmodel import Session

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.telemetry.domain.repositories.implementations import knowledge_statistics_repository_impl as subject


def test_category_sources_are_read_only_and_exclude_foreign_tenant(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=1,
                    knowledge_id=10,
                    tenant_id=1,
                    file_name="管理入口",
                    reference_document_id=91,
                    entry_type="manager",
                    entry_status="active",
                    status=2,
                    split_rule=json.dumps({"file_category_code": "POL"}),
                ),
                KnowledgeFile(
                    id=2,
                    knowledge_id=20,
                    tenant_id=1,
                    file_name="共享入口",
                    reference_document_id=91,
                    entry_type="share",
                    entry_status="active",
                    status=2,
                    file_encoding="SG-POL-EM-000001",
                ),
                KnowledgeFile(
                    id=9,
                    knowledge_id=90,
                    tenant_id=2,
                    file_name="其它租户",
                    reference_document_id=92,
                    entry_type="manager",
                    entry_status="active",
                    status=2,
                ),
                KnowledgeDocument(
                    id=91, tenant_id=1, knowledge_id=10, primary_version_id=901, lifecycle_status="active"
                ),
                KnowledgeDocument(
                    id=92, tenant_id=2, knowledge_id=90, primary_version_id=902, lifecycle_status="active"
                ),
                KnowledgeDocumentVersion(id=901, document_id=91, knowledge_file_id=1, version_no=1),
                KnowledgeDocumentVersion(id=902, document_id=92, knowledge_file_id=9, version_no=1),
            ]
        )
        session.commit()
        statements = []

        @event.listens_for(engine, "before_cursor_execute")
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        @contextmanager
        def selected_session():
            yield session

        monkeypatch.setattr(subject, "get_sync_db_session", selected_session)
        monkeypatch.setattr(subject, "get_current_tenant_id", lambda: 1)
        result = subject.KnowledgeStatisticsRepositoryImpl.category_audit_sources([1, 2, 9], [91, 92])
        assert set(result["files"]) == {1, 2} and set(result["documents"]) == {91}
        assert result["documents"][91]["primary_version_file_id"] == 1
        assert result["files"][1]["category_source"] == "split_rule"
        assert result["files"][2]["category_source"] == "file_encoding"
        assert [row["file_id"] for row in result["entries"][91]] == [1, 2]
        assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    engine.dispose()


def test_category_sources_reject_unbounded_batch_before_database(monkeypatch):
    monkeypatch.setattr(subject, "get_current_tenant_id", lambda: 1)
    with pytest.raises(ValueError, match="400"):
        subject.KnowledgeStatisticsRepositoryImpl.category_audit_sources(list(range(1, 402)), [])

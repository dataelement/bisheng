"""Tests for the KnowledgeDocumentVersion SQLModel."""
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
    KnowledgeDocumentVersionBase,
)


def test_version_minimal_instantiation():
    v = KnowledgeDocumentVersion(
        document_id=1, knowledge_file_id=100, version_no=1
    )
    assert v.document_id == 1
    assert v.knowledge_file_id == 100
    assert v.version_no == 1
    assert v.is_primary is False
    assert v.id is None


def test_version_primary_flag():
    v = KnowledgeDocumentVersion(
        document_id=1, knowledge_file_id=100, version_no=1, is_primary=True
    )
    assert v.is_primary is True


def test_version_table_name():
    assert KnowledgeDocumentVersion.__tablename__ == "knowledge_document_version"


def test_base_class_has_no_id():
    assert "id" not in KnowledgeDocumentVersionBase.model_fields


def test_unique_constraint_on_document_id_and_version_no():
    from sqlalchemy import UniqueConstraint
    constraints = [
        c for c in KnowledgeDocumentVersion.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert any(
        {col.name for col in c.columns} == {"document_id", "version_no"}
        for c in constraints
    ), "Expected UNIQUE constraint on (document_id, version_no)"

"""Tests for the KnowledgeDocument SQLModel."""
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentBase,
)


def test_knowledge_document_minimal_instantiation():
    doc = KnowledgeDocument(knowledge_id=42)
    assert doc.knowledge_id == 42
    assert doc.file_level_path is None
    assert doc.level == 0
    assert doc.primary_version_id is None
    assert doc.id is None  # not yet persisted


def test_knowledge_document_with_folder():
    doc = KnowledgeDocument(
        knowledge_id=5,
        file_level_path="/100/200",
        level=2,
        primary_version_id=99,
    )
    assert doc.file_level_path == "/100/200"
    assert doc.level == 2
    assert doc.primary_version_id == 99


def test_knowledge_document_table_name():
    assert KnowledgeDocument.__tablename__ == "knowledge_document"


def test_base_class_has_no_id():
    assert "id" not in KnowledgeDocumentBase.model_fields

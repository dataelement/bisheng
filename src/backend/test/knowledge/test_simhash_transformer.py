"""Tests for SimHashTransformer."""

from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.transformer.simhash import SimHashTransformer


def test_simhash_transformer_writes_hex_to_knowledge_file():
    kf = KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf",
                       file_type=1, status=2, simhash=None)
    t = SimHashTransformer(knowledge_file=kf)

    docs = [
        Document(page_content="知识空间文件版本管理的设计要点"),
        Document(page_content="逻辑文档归并多个物理文件版本"),
    ]
    out = t.transform_documents(docs)
    # documents returned unchanged
    assert len(out) == 2
    assert out[0].page_content == docs[0].page_content
    # simhash written to knowledge file
    assert kf.simhash is not None
    assert len(kf.simhash) == 16
    assert all(c in "0123456789abcdef" for c in kf.simhash)


def test_simhash_transformer_idempotent_skips_when_present():
    """If simhash is already populated, don't recompute (re-parse safety)."""
    kf = KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf",
                       file_type=1, status=2, simhash="cafebabecafebabe")
    t = SimHashTransformer(knowledge_file=kf)

    t.transform_documents([Document(page_content="different content")])
    assert kf.simhash == "cafebabecafebabe"  # unchanged


def test_simhash_transformer_empty_documents_writes_zero_hash():
    kf = KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf",
                       file_type=1, status=2, simhash=None)
    t = SimHashTransformer(knowledge_file=kf)

    t.transform_documents([])
    assert kf.simhash == "0" * 16


def test_simhash_transformer_returns_documents_unchanged():
    """Critical invariant: transformer must not modify document content."""
    kf = KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf",
                       file_type=1, status=2, simhash=None)
    t = SimHashTransformer(knowledge_file=kf)

    original = [Document(page_content="content A", metadata={"k": "v"}),
                Document(page_content="content B")]
    out = t.transform_documents(original)
    assert len(out) == 2
    assert out[0].page_content == "content A"
    assert out[0].metadata == {"k": "v"}
    assert out[1].page_content == "content B"

"""Tests for AbstractTransformer.

The abstract (summary) is a best-effort enhancement layered on top of the core
file-parsing flow. A failing summary LLM call must NOT fail the whole file: the
transformer should swallow the error, leave the abstract empty, and let parsing
continue. These tests pin that contract plus the happy path / no-llm early exit.
"""

from types import SimpleNamespace

from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer


class _StubLLM:
    """Minimal stand-in for a chat model: returns canned content or raises."""

    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self._content = content
        self._exc = exc

    def invoke(self, messages):
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(content=self._content)


def _make_transformer(kf: KnowledgeFile, llm, abstract_prompt: str | None = None) -> AbstractTransformer:
    t = AbstractTransformer(invoke_user_id=1, knowledge_file=kf)
    # llm_config is a cached_property (non-data descriptor); an instance
    # attribute shadows it, so we can inject the (llm, config) tuple directly
    # without touching KnowledgeUtils / LLMService.
    t.llm_config = (llm, SimpleNamespace(abstract_prompt=abstract_prompt))
    return t


def _new_kf() -> KnowledgeFile:
    return KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf", file_type=1, status=2)


def test_abstract_llm_failure_leaves_abstract_empty_and_does_not_raise():
    """Core fix: a content-audit / 400 / timeout failure must not blow up parsing."""
    kf = _new_kf()
    exc = RuntimeError("Error code: 400 - {'error': {'type': 'TEXT_AUDIT_QUESTION_NOT_PASS'}}")
    t = _make_transformer(kf, _StubLLM(exc=exc))

    docs = [Document(page_content="一些会触发内容审核拒答的文档正文")]
    out = t.transform_documents(docs)

    # No exception propagated; documents returned intact.
    assert len(out) == 1
    assert out[0].page_content == docs[0].page_content
    # Abstract degraded to empty rather than failing the file.
    assert out[0].metadata["abstract"] == ""
    assert kf.abstract == ""


def test_abstract_llm_success_sets_parsed_abstract():
    """Happy path regression: a normal LLM response is parsed and stored."""
    kf = _new_kf()
    t = _make_transformer(kf, _StubLLM(content="【摘要】这是一段文档摘要。"))

    docs = [Document(page_content="文档正文内容")]
    out = t.transform_documents(docs)

    assert out[0].metadata["abstract"] == "【摘要】这是一段文档摘要。"
    assert kf.abstract == "【摘要】这是一段文档摘要。"


def test_no_llm_configured_returns_documents_unchanged():
    """When the abstract LLM is not configured, skip entirely (early exit)."""
    kf = _new_kf()
    t = _make_transformer(kf, llm=None)

    docs = [Document(page_content="文档正文", metadata={"k": "v"})]
    out = t.transform_documents(docs)

    assert out[0].page_content == "文档正文"
    assert out[0].metadata == {"k": "v"}  # no "abstract" key injected
    assert kf.abstract is None

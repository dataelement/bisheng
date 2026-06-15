"""Pipeline-level integration tests for best-effort abstract generation.

Unlike test_abstract_transformer.py (which unit-tests the transformer in
isolation), these drive a real NormalPipeline end to end — loader -> the real
AbstractTransformer -> vector store — with the summary LLM *API mocked*. They
pin the production-shaped contract: a failing summary API must not stop the
file from being ingested, while genuine core errors (e.g. an oversized-chunk
failure at the ingest step) must still surface.
"""

from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.base import NormalPipeline
from bisheng.knowledge.rag.pipeline.transformer.abstract import AbstractTransformer
from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineStage


class _StubLLM:
    """Mocked chat-model API: returns canned content or raises like a real one."""

    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self._content = content
        self._exc = exc

    def invoke(self, messages):
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(content=self._content)


class _StubLoader:
    """Duck-typed loader; NormalPipeline only calls .load()."""

    def __init__(self, docs):
        self._docs = list(docs)

    def load(self):
        return self._docs


class _RecordingVectorStore:
    """Records ingested docs, or simulates a core ingest failure."""

    def __init__(self, fail: bool = False):
        self.added: list[Document] = []
        self._fail = fail

    def add_documents(self, docs, **kwargs):
        if self._fail:
            # Mirrors a real core failure surfaced at ingest time, e.g.
            # "Segmentation results are too long, try using more splitters".
            raise RuntimeError("Segmentation results are too long, try using more splitters")
        self.added.extend(docs)
        return [str(i) for i in range(len(docs))]


def _abstract_transformer(kf: KnowledgeFile, llm) -> AbstractTransformer:
    t = AbstractTransformer(invoke_user_id=1, knowledge_file=kf)
    # Inject the (mocked llm, config) tuple, shadowing the cached_property so
    # KnowledgeUtils / LLMService are never touched.
    t.llm_config = (llm, SimpleNamespace(abstract_prompt=None))
    return t


def _new_kf() -> KnowledgeFile:
    return KnowledgeFile(id=1, knowledge_id=1, file_name="test.pdf", file_type=1, status=2)


def test_pipeline_ingests_when_summary_api_fails():
    """The whole point: a failing summary API does NOT block ingestion."""
    kf = _new_kf()
    exc = RuntimeError("Error code: 400 - {'error': {'type': 'TEXT_AUDIT_QUESTION_NOT_PASS'}}")
    transformer = _abstract_transformer(kf, _StubLLM(exc=exc))
    vs = _RecordingVectorStore()
    docs = [Document(page_content="正文一"), Document(page_content="正文二")]

    pipeline = NormalPipeline(loader=_StubLoader(docs), transformers=[transformer], vector_store=[vs])
    result = pipeline.run(PipelineConfig())

    # Reached full ingest despite the summary API failure.
    assert result.stage_reached == PipelineStage.INGEST
    # Documents actually made it to the vector store (parsing continued).
    assert len(vs.added) == 2
    # Summary degraded to empty rather than failing the file.
    assert kf.abstract == ""
    assert all(d.metadata.get("abstract") == "" for d in result.documents)


def test_pipeline_populates_abstract_when_summary_api_succeeds():
    """Happy-path control: a working summary API populates the abstract."""
    kf = _new_kf()
    transformer = _abstract_transformer(kf, _StubLLM(content="这是文档摘要。"))
    vs = _RecordingVectorStore()
    docs = [Document(page_content="正文")]

    pipeline = NormalPipeline(loader=_StubLoader(docs), transformers=[transformer], vector_store=[vs])
    result = pipeline.run(PipelineConfig())

    assert result.stage_reached == PipelineStage.INGEST
    assert len(vs.added) == 1
    assert kf.abstract == "这是文档摘要。"


def test_pipeline_still_fails_on_core_ingest_error():
    """Boundary guard: real core errors (ingest) must still fail the parse.

    Confirms the fix isolates *summary* failures only and does not swallow
    genuine parsing/ingestion errors.
    """

    kf = _new_kf()
    transformer = _abstract_transformer(kf, _StubLLM(content="摘要"))
    vs = _RecordingVectorStore(fail=True)
    docs = [Document(page_content="正文")]

    pipeline = NormalPipeline(loader=_StubLoader(docs), transformers=[transformer], vector_store=[vs])
    with pytest.raises(RuntimeError, match="Segmentation results are too long"):
        pipeline.run(PipelineConfig())

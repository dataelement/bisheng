"""Linsight uploaded-file parsing no longer vectorises into milvus/es.

Task execution reads each uploaded file's parsed markdown directly from the
agent workspace (``read_file``); the old ``col_linsight_file_*`` vectors were
write-only since ``search_linsight_file`` was removed. ``_parse_file`` must now
only parse the file and upload its markdown to MinIO — no embedding / milvus / es
write — and the ``_process_vector_storage`` helper must be gone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl


class _FakePipeline:
    def __init__(self, **_kwargs):
        self.loader = SimpleNamespace()

    async def arun(self):
        return SimpleNamespace(documents=[SimpleNamespace(page_content="hello"), SimpleNamespace(page_content="world")])


async def test_parse_file_uploads_markdown_without_vector_write(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _FakePipeline, raising=False)
    fake_minio = AsyncMock()
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.get_minio_storage",
        AsyncMock(return_value=fake_minio),
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.async_calculate_md5",
        AsyncMock(return_value="deadbeef"),
    )
    # Hard guard: any attempt to build a vector store must fail the test.
    milvus_spy = Mock(side_effect=AssertionError("milvus write must not happen"))
    es_spy = Mock(side_effect=AssertionError("es write must not happen"))
    monkeypatch.setattr("bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_milvus_vectorstore", milvus_spy)
    monkeypatch.setattr("bisheng.knowledge.domain.knowledge_rag.KnowledgeRag.init_es_vectorstore", es_spy)

    result = await LinsightWorkbenchImpl._parse_file(1, "fid123", "/tmp/x.docx", "x.docx")

    assert result["parsing_status"] == "completed"
    assert result["markdown_filename"] == "fid123.md"
    assert result["markdown_file_path"] == "fid123.md"
    # Vector-store-only fields are gone; the agent reads markdown from the workspace.
    assert "collection_name" not in result
    assert "embedding_model_id" not in result
    fake_minio.put_object_tmp.assert_awaited_once()
    milvus_spy.assert_not_called()
    es_spy.assert_not_called()


def test_vector_storage_helper_removed():
    assert not hasattr(LinsightWorkbenchImpl, "_process_vector_storage")
    assert not hasattr(LinsightWorkbenchImpl, "COLLECTION_NAME_PREFIX")

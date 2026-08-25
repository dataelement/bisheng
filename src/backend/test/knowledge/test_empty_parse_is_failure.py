"""A parse that produced no chunks must be recorded as FAILED, never SUCCESS.

Field case (knowledge space 142, file 860): an .xlsx openpyxl could not open was
listed as 解析成功 while the space answered 「没有找到相关内容」 to every question.
Zero chunks had reached Milvus or ES — the collection was never even created —
but ``addEmbedding`` sets SUCCESS on any pipeline run that does not raise, so the
file looked healthy everywhere except where it was searched.

The loader that swallowed the error is fixed separately
(:mod:`test_xlsx_style_repair`). This test pins the backstop: whatever the reason
a parse yields nothing — a loader that bailed, a scanned page with no extractable
text, a future format we mis-handle — the outcome the user sees is a failure with
a reason, not a silent success.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from bisheng.api.services import knowledge_imp
from bisheng.common.errcode.knowledge import KnowledgeFileEmptyError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.rag.pipeline.types import PipelineResult, PipelineStage


def _file() -> KnowledgeFile:
    return KnowledgeFile(
        id=860,
        knowledge_id=142,
        file_name="大豆链-功能清单.xlsx",
        user_id=1,
        updater_id=1,
        status=KnowledgeFileStatus.PROCESSING.value,
        object_name="original/860.xlsx",
    )


@pytest.fixture
def harness(monkeypatch):
    """Stub everything around the pipeline; the pipeline's OUTPUT is the subject."""
    saved: list[KnowledgeFile] = []

    monkeypatch.setattr(knowledge_imp.KnowledgeDao, "query_by_id", staticmethod(lambda _id: MagicMock(type=1)))
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag, "init_knowledge_milvus_vectorstore_sync", staticmethod(lambda *a, **k: MagicMock())
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeRag, "init_knowledge_es_vectorstore_sync", staticmethod(lambda *a, **k: MagicMock())
    )
    monkeypatch.setattr(
        knowledge_imp.KnowledgeUtils, "ensure_milvus_schema_ready", staticmethod(lambda *a, **k: MagicMock())
    )
    monkeypatch.setattr(knowledge_imp.KnowledgeFileDao, "update", staticmethod(lambda f: saved.append(f) or f))
    monkeypatch.setattr(knowledge_imp.telemetry_service, "log_event_sync", lambda *a, **k: None)
    return saved


def _run_with_documents(monkeypatch, documents):
    pipeline = MagicMock()
    pipeline.run.return_value = PipelineResult(
        stage_reached=PipelineStage.INGEST, documents=documents, duration_seconds=0.1
    )
    monkeypatch.setattr(knowledge_imp, "KnowledgeFilePipeline", lambda *a, **k: pipeline)
    db_file = _file()
    knowledge_imp.addEmbedding(knowledge_id=142, knowledge_files=[db_file])
    return db_file


def test_zero_chunks_is_recorded_as_a_failure(monkeypatch, harness):
    db_file = _run_with_documents(monkeypatch, [])
    assert db_file.status == KnowledgeFileStatus.FAILED.value
    # And the reason is carried to the UI, not just to a log line.
    assert json.loads(db_file.remark)["status_code"] == KnowledgeFileEmptyError.Code


def test_a_parse_that_produced_chunks_still_succeeds(monkeypatch, harness):
    db_file = _run_with_documents(monkeypatch, [MagicMock()])
    assert db_file.status == KnowledgeFileStatus.SUCCESS.value


def test_the_outcome_is_persisted_either_way(monkeypatch, harness):
    """The status only matters if it is written — the file row is what the list
    page and the space search both read."""
    _run_with_documents(monkeypatch, [])
    assert [f.status for f in harness] == [KnowledgeFileStatus.FAILED.value]

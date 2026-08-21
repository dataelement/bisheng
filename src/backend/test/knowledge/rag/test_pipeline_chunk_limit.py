from types import SimpleNamespace

import pytest

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeFileChunkMaxError
from bisheng.knowledge.rag import base_file_pipeline
from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline


def _set_chunk_limit(monkeypatch, value: int) -> None:
    knowledge_conf = SimpleNamespace(chunking=SimpleNamespace(max_chunk_chars=value))
    monkeypatch.setattr(base_file_pipeline.settings, "get_knowledge", lambda: knowledge_conf)


def test_pipeline_passes_system_chunk_limit_to_excel_loader(monkeypatch, tmp_path):
    _set_chunk_limit(monkeypatch, 4096)
    rule = FileProcessBase(knowledge_id=1, excel_rule=ExcelRule())
    pipeline = TempFilePipeline(1, str(tmp_path / "wide.xlsx"), "wide.xlsx", rule)
    pipeline.tmp_dir = str(tmp_path)
    pipeline.__dict__["file_metadata"] = {}

    loader = pipeline._init_excel_loader()

    assert loader.max_chunk_chars == 4096


def test_pipeline_rejects_requested_chunk_size_above_system_limit(monkeypatch, tmp_path):
    _set_chunk_limit(monkeypatch, 1500)
    rule = FileProcessBase(knowledge_id=1, chunk_size=1501)

    with pytest.raises(KnowledgeFileChunkMaxError, match="system limit of 1500"):
        TempFilePipeline(1, str(tmp_path / "doc.txt"), "doc.txt", rule)

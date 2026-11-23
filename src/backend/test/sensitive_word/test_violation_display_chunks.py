"""Violation files keep parse segments for the detail view, outside the retrieval index."""

import importlib.util
import json
from pathlib import Path

from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline


class _Redis:
    def __init__(self):
        self.store = {}

    def delete(self, key):
        self.store.pop(key, None)

    def hset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        bucket = self.store.setdefault(name, {})
        if mapping:
            bucket.update(mapping)
        elif key is not None:
            bucket[key] = value

    def hgetall(self, name):
        return dict(self.store.get(name, {}))


class _Chunk:
    def __init__(self, text, index):
        self.page_content = text
        self.metadata = {"chunk_index": index, "bbox": "", "page": 1}


def _file():
    return KnowledgeFile(
        id=98309,
        knowledge_id=4278,
        file_name="哈哈哈.docx",
        status=KnowledgeFileStatus.VIOLATION.value,
        parse_type="un_etl4lm",
        split_rule=json.dumps(
            {
                "knowledge_id": 4278,
                "chunk_size": 8,
                "chunk_overlap": 0,
                "separator": ["。"],
                "separator_rule": ["after"],
            },
            ensure_ascii=False,
        ),
    )


def test_segment_for_display_splits_loaded_text_without_a_vector_store():
    pipeline = KnowledgeFilePipeline(invoke_user_id=1, db_file=_file())
    docs = pipeline.segment_for_display([Document(page_content="一二三四五六七八。九十十一十二十三。")])

    assert [doc.metadata["chunk_index"] for doc in docs] == list(range(len(docs)))
    assert len(docs) >= 2
    assert "".join(doc.page_content for doc in docs).startswith("一二三四五六七八")


def _real_utils(monkeypatch):
    # The test harness installs a KnowledgeUtils placeholder. Run the real store.
    path = Path(__file__).resolve().parents[2] / "bisheng/knowledge/domain/services/knowledge_utils.py"
    spec = importlib.util.spec_from_file_location("_violation_display_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = importlib.import_module("bisheng.knowledge.domain.services.knowledge_service")
    monkeypatch.setattr(service, "KnowledgeUtils", module.KnowledgeUtils)
    return module


def test_violation_detail_reads_saved_segments_and_does_not_rebuild(monkeypatch):
    redis = _Redis()
    utils = _real_utils(monkeypatch)
    monkeypatch.setattr(utils, "get_redis_client_sync", lambda: redis)
    file = _file()
    utils.KnowledgeUtils.save_violation_display_chunks(file.id, [_Chunk("知识库测试文档", 0), _Chunk("命中词", 1)])
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [file],
    )
    calls = {"ensure": 0}

    def ensure(db_file):
        calls["ensure"] += 1

    monkeypatch.setattr("bisheng.api.services.knowledge_imp.ensure_violation_display_chunks", ensure)

    page, total = KnowledgeService._violation_display_chunks(4278, [file.id], None, 1, 10)
    matched, matched_total = KnowledgeService._violation_display_chunks(4278, [file.id], "命中词", 1, 10)

    assert calls["ensure"] == 0
    assert total == 2
    assert [one.text for one in page] == ["知识库测试文档", "命中词"]
    assert matched_total == 1
    assert matched[0].text == "命中词"
    assert matched[0].metadata.document_id == file.id


def test_missing_violation_segments_are_built_once_for_the_detail_view(monkeypatch):
    redis = _Redis()
    utils = _real_utils(monkeypatch)
    monkeypatch.setattr(utils, "get_redis_client_sync", lambda: redis)
    file = _file()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [file],
    )

    def ensure(db_file):
        utils.KnowledgeUtils.save_violation_display_chunks(db_file.id, [_Chunk("解析分段", 0)])

    monkeypatch.setattr("bisheng.api.services.knowledge_imp.ensure_violation_display_chunks", ensure)

    page, total = KnowledgeService._violation_display_chunks(4278, [file.id], "", 1, 10)

    assert total == 1
    assert page[0].text == "解析分段"


def test_non_violation_file_does_not_read_the_display_store(monkeypatch):
    file = _file()
    file.status = KnowledgeFileStatus.SUCCESS.value
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeFileDao.get_file_by_ids",
        lambda ids: [file],
    )

    assert KnowledgeService._violation_display_chunks(4278, [file.id], None, 1, 10) is None

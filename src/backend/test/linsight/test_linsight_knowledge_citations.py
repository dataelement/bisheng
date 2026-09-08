"""F047: SearchKnowledgeBase.base_search registers RAG citations for the model."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.tool.domain.langchain import linsight_knowledge as knowledge_tool
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase


def _hit(**overrides) -> Document:
    metadata = {
        "file_id": 11,
        "file_name": "北京市大气污染治理成效年度总结.pdf",
        "page": 3,
        "bbox": '{"x":1}',
        "chunk_index": 1,
        "pk": "pk-1",
    }
    metadata.update(overrides)
    return Document(page_content="PM2.5 年均浓度 28.6 微克/立方米。", metadata=metadata)


@pytest.fixture
def citation_deps(monkeypatch: pytest.MonkeyPatch):
    cached = {}

    async def fake_cache(items):
        cached["items"] = items
        return items

    def fake_format(doc, kb_name: str = "") -> str:
        meta = getattr(doc, "metadata", {}) or {}
        return (
            f"<chunk_id>{meta.get('citation_key') or ''}</chunk_id>\n"
            f"<knowledge_base_id>{meta.get('knowledge_id') or ''}</knowledge_base_id>\n"
            f"<knowledge_base_name>{kb_name}</knowledge_base_name>"
        )

    monkeypatch.setattr(knowledge_tool, "cache_citation_registry_items", fake_cache)
    monkeypatch.setattr(
        knowledge_tool.KnowledgeUtils,
        "format_retrieved_chunk",
        staticmethod(fake_format),
        raising=False,
    )
    monkeypatch.setattr(
        KnowledgeDao,
        "get_list_by_ids",
        classmethod(lambda cls, ids: [SimpleNamespace(id=99, name="政策文件")]),
    )
    return cached


async def test_base_search_annotates_and_caches(citation_deps):
    tool = SearchKnowledgeBase()
    vector = SimpleNamespace(asimilarity_search=AsyncMock(return_value=[_hit()]))

    raw = await tool.base_search(vector, "PM2.5", 2, knowledge_id=99, knowledge_name="政策文件")
    payload = json.loads(raw)

    assert payload["状态"] == "成功"
    chunk = payload["结果"][0]
    assert "<chunk_id>" in chunk
    assert "knowledgesearch_" in chunk
    assert "<knowledge_base_id>99</knowledge_base_id>" in chunk
    assert "<knowledge_base_name>政策文件</knowledge_base_name>" in chunk
    items = citation_deps["items"]
    assert items
    assert items[0].sourcePayload.documentId == 11
    assert items[0].sourcePayload.knowledgeId == 99
    assert items[0].accessScope == "per_user"
    # knowledge_id must not leak into milvus kwargs
    assert "knowledge_id" not in vector.asimilarity_search.await_args.kwargs


async def test_base_search_annotate_failure_returns_bare_chunks(monkeypatch: pytest.MonkeyPatch):
    def boom(_docs):
        raise RuntimeError("annotate exploded")

    monkeypatch.setattr(knowledge_tool, "annotate_rag_documents_with_citations", boom)
    tool = SearchKnowledgeBase()
    vector = SimpleNamespace(asimilarity_search=AsyncMock(return_value=[_hit()]))

    raw = await tool.base_search(vector, "q", 1, knowledge_id=99)
    payload = json.loads(raw)

    assert payload["状态"] == "成功"
    assert payload["结果"] == ["PM2.5 年均浓度 28.6 微克/立方米。"]


async def test_base_search_empty_hits_is_no_result():
    tool = SearchKnowledgeBase()
    vector = SimpleNamespace(asimilarity_search=AsyncMock(return_value=[]))

    raw = await tool.base_search(vector, "q", 1)
    assert json.loads(raw)["状态"] == "无结果"

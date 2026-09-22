"""F069 T018: retrieval results show the model a short handle, not the registry key.

AC-07 (``<ref>S3</ref>`` / ``"ref": "S7"`` replace the ids), AC-17 (allocation
failure keeps the F047 shape), AC-18 (scope disabled keeps the F047 shape).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.citation.domain.services import citation_handle_service as handle_svc
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import _LinsightWebCitationWrapper
from bisheng.tool.domain.langchain import linsight_knowledge as knowledge_tool
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase


class _Scope:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.session_id = "chat-1"
        self.svid = "sv-1"
        self.seen: list = []
        self.handles: dict = {}
        self.key_to_handle: dict = {}
        self.entries: list = []

    async def record_seen(self, items):
        self.seen.extend(items)

    def register_handle(self, handle, key, entry):
        self.handles[handle] = key
        self.key_to_handle[key] = handle
        self.entries.append(entry)


def _fake_assign(mapping_by_index):
    async def _assign(scope, items):
        out = {}
        for idx, item in enumerate(items):
            if idx in mapping_by_index:
                out[item.key] = mapping_by_index[idx]
        return out

    return _assign


def _hit(idx: int) -> Document:
    return Document(
        page_content=f"chunk {idx}",
        metadata={"document_id": 11, "file_name": "总结.pdf", "page": idx, "bbox": "{}", "chunk_index": idx, "pk": f"pk-{idx}"},
    )


@pytest.fixture
def kb_deps(monkeypatch: pytest.MonkeyPatch):
    async def fake_cache(items):
        return items

    def fake_format(doc, kb_name: str = "") -> str:
        meta = getattr(doc, "metadata", {}) or {}
        return f"<chunk_id>{meta.get('citation_key') or ''}</chunk_id>\n<paragraph_content>{doc.page_content}</paragraph_content>"

    monkeypatch.setattr(knowledge_tool, "cache_citation_registry_items", fake_cache)
    monkeypatch.setattr(knowledge_tool.KnowledgeUtils, "format_retrieved_chunk", staticmethod(fake_format), raising=False)
    monkeypatch.setattr(KnowledgeDao, "get_list_by_ids", classmethod(lambda cls, ids: [SimpleNamespace(id=99, name="政策")]))


async def _search(tool):
    vector = SimpleNamespace(asimilarity_search=AsyncMock(return_value=[_hit(1), _hit(2)]))
    return json.loads(await tool.base_search(vector, "q", 2, knowledge_id=99, knowledge_name="政策"))


async def test_kb_chunks_carry_ref_handles(kb_deps, monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({0: "S1", 1: "S2"}))
    tool = SearchKnowledgeBase(citation_scope=_Scope())

    payload = await _search(tool)

    assert "<ref>S1</ref>" in payload["结果"][0]
    assert "<ref>S2</ref>" in payload["结果"][1]
    assert "<chunk_id>" not in payload["结果"][0]
    assert "chunk 1" in payload["结果"][0]  # the rest of the template is untouched


async def test_kb_partial_allocation_keeps_raw_key_for_the_rest(kb_deps, monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({0: "S1"}))
    tool = SearchKnowledgeBase(citation_scope=_Scope())

    payload = await _search(tool)

    assert "<ref>S1</ref>" in payload["结果"][0]
    assert "<chunk_id>knowledgesearch_" in payload["结果"][1]


async def test_kb_allocation_failure_or_disabled_scope_keeps_f047_shape(kb_deps, monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({}))
    assert "<chunk_id>knowledgesearch_" in (await _search(SearchKnowledgeBase(citation_scope=_Scope())))["结果"][0]

    called = {"n": 0}

    async def _never(scope, items):
        called["n"] += 1
        return {}

    monkeypatch.setattr(handle_svc, "assign_handles", _never)
    assert "<chunk_id>knowledgesearch_" in (await _search(SearchKnowledgeBase(citation_scope=_Scope(enabled=False))))["结果"][0]
    assert called["n"] == 0


class _WebIn(BaseModel):
    query: str = Field(default="")


class _FakeWeb(BaseTool):
    name: str = "web_search"
    description: str = "search the web"
    args_schema: type[BaseModel] = _WebIn
    payload: str = json.dumps([
        {"title": "A", "url": "https://a.com/1", "snippet": "x"},
        {"title": "B", "url": "https://b.com/2", "snippet": "y"},
    ])

    def _run(self, query: str = "") -> str:
        return self.payload

    async def _arun(self, query: str = "") -> str:
        return self.payload


@pytest.fixture
def cache_web(monkeypatch: pytest.MonkeyPatch):
    async def fake_cache(items):
        return items

    monkeypatch.setattr("bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items", fake_cache)


async def test_web_results_carry_ref_and_drop_key(cache_web, monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({0: "S7", 1: "S8"}))
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=_Scope())

    results = json.loads(await wrapped.ainvoke({"query": "q"}))

    assert [r["ref"] for r in results] == ["S7", "S8"]
    assert all("citation_key" not in r and "itemId" not in r for r in results)
    assert results[0]["title"] == "A"


async def test_web_allocation_failure_keeps_citation_key(cache_web, monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({}))
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=_Scope())

    results = json.loads(await wrapped.ainvoke({"query": "q"}))

    assert all("citation_key" in r and "ref" not in r for r in results)


async def test_web_disabled_scope_keeps_citation_key(cache_web, monkeypatch):
    async def _never(scope, items):
        raise AssertionError("must not allocate when the scope is disabled")

    monkeypatch.setattr(handle_svc, "assign_handles", _never)
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=_Scope(enabled=False))

    results = json.loads(await wrapped.ainvoke({"query": "q"}))

    assert all("citation_key" in r for r in results)
    assert agent_factory is not None

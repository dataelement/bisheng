"""F069 T003/T005: the retrieval tools report every hit to the run's citation scope.

Both the knowledge-base tool and the web-search wrapper call ``scope.record_seen``
right after registering hits, and the researcher sub-agent reuses the SAME tool
instances, so sources retrieved inside the sub-graph are counted too (AC-02).
A scope failure must never break the tool (AC-25); with no scope bound the tools
behave exactly as before.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _LinsightWebCitationWrapper,
    _subagent_tools,
    _wrap_linsight_web_citation_tools,
)
from bisheng.tool.domain.langchain import linsight_knowledge as knowledge_tool
from bisheng.tool.domain.langchain.linsight_knowledge import SearchKnowledgeBase


class _RecordingScope:
    def __init__(self):
        self.calls: list = []
        self.enabled = True
        self.seen_keys: set = set()

    async def record_seen(self, items):
        self.calls.append(list(items))


class _BoomScope(_RecordingScope):
    async def record_seen(self, items):
        raise RuntimeError("scope exploded")


def _hit() -> Document:
    return Document(
        page_content="PM2.5 年均浓度 28.6 微克/立方米。",
        metadata={
            "document_id": 11,
            "file_name": "总结.pdf",
            "page": 3,
            "bbox": "{}",
            "chunk_index": 1,
            "pk": "pk-1",
        },
    )


@pytest.fixture
def kb_deps(monkeypatch: pytest.MonkeyPatch):
    cached = {}

    async def fake_cache(items):
        cached["items"] = items
        return items

    def fake_format(doc, kb_name: str = "") -> str:
        meta = getattr(doc, "metadata", {}) or {}
        return f"<chunk_id>{meta.get('citation_key') or ''}</chunk_id>"

    monkeypatch.setattr(knowledge_tool, "cache_citation_registry_items", fake_cache)
    monkeypatch.setattr(
        knowledge_tool.KnowledgeUtils, "format_retrieved_chunk", staticmethod(fake_format), raising=False
    )
    monkeypatch.setattr(
        KnowledgeDao, "get_list_by_ids", classmethod(lambda cls, ids: [SimpleNamespace(id=99, name="政策")])
    )
    return cached


async def _kb_search(tool: SearchKnowledgeBase) -> dict:
    vector = SimpleNamespace(asimilarity_search=AsyncMock(return_value=[_hit()]))
    return json.loads(await tool.base_search(vector, "PM2.5", 2, knowledge_id=99, knowledge_name="政策"))


async def test_kb_tool_reports_hits_to_scope(kb_deps):
    scope = _RecordingScope()
    tool = SearchKnowledgeBase(citation_scope=scope)

    payload = await _kb_search(tool)

    assert payload["状态"] == "成功"
    assert len(scope.calls) == 1
    assert scope.calls[0] == kb_deps["items"]
    assert scope.calls[0][0].citationId.startswith("knowledgesearch_")


async def test_kb_tool_without_scope_is_unchanged(kb_deps):
    tool = SearchKnowledgeBase()

    payload = await _kb_search(tool)

    assert payload["状态"] == "成功"
    assert "<chunk_id>knowledgesearch_" in payload["结果"][0]


async def test_kb_tool_scope_failure_returns_bare_chunks(kb_deps):
    tool = SearchKnowledgeBase(citation_scope=_BoomScope())

    payload = await _kb_search(tool)

    # the existing annotate-failure fallback catches it: task keeps going
    assert payload["状态"] == "成功"
    assert payload["结果"] == ["PM2.5 年均浓度 28.6 微克/立方米。"]


class _WebIn(BaseModel):
    query: str = Field(default="")


class _FakeWeb(BaseTool):
    name: str = "web_search"
    description: str = "search the web"
    args_schema: type[BaseModel] = _WebIn
    payload: str = json.dumps([{"title": "PM2.5", "url": "https://example.com/pm25", "snippet": "x"}])

    def _run(self, query: str = "") -> str:
        return self.payload

    async def _arun(self, query: str = "") -> str:
        return self.payload


@pytest.fixture
def cache_web(monkeypatch: pytest.MonkeyPatch):
    cached = {}

    async def fake_cache(items):
        cached["items"] = items
        return items

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items", fake_cache
    )
    return cached


async def test_web_wrapper_reports_hits_to_scope(cache_web):
    scope = _RecordingScope()
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=scope)

    out = await wrapped.ainvoke({"query": "pm25"})

    assert "citation_key" in out
    assert len(scope.calls) == 1
    assert scope.calls[0] == cache_web["items"]
    assert scope.calls[0][0].sourcePayload.url == "https://example.com/pm25"


async def test_web_wrapper_without_scope_is_unchanged(cache_web):
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb())

    out = await wrapped.ainvoke({"query": "pm25"})

    assert "citation_key" in out
    assert cache_web["items"]


async def test_web_wrapper_scope_failure_returns_bare(cache_web):
    wrapped = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=_BoomScope())

    out = await wrapped.ainvoke({"query": "pm25"})

    assert json.loads(out) == json.loads(_FakeWeb().payload)


def test_wrap_tools_threads_scope_to_web_only():
    scope = _RecordingScope()
    kb = SearchKnowledgeBase()
    wrapped = _wrap_linsight_web_citation_tools([kb, _FakeWeb()], scope=scope)

    assert wrapped[0] is kb
    assert isinstance(wrapped[1], _LinsightWebCitationWrapper)
    assert wrapped[1].scope is scope


def test_subagent_reuses_the_same_tool_instances():
    kb = SearchKnowledgeBase()
    web = _LinsightWebCitationWrapper.wrap(_FakeWeb(), scope=_RecordingScope())

    sub = _subagent_tools([kb, web])

    assert any(t is kb for t in sub)
    assert any(t is web for t in sub)


async def test_create_linsight_agent_binds_scope_to_tools(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(SimpleNamespace(), False)))
    # keep the factory off the DB-backed system config
    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    scope = _RecordingScope()
    kb = SearchKnowledgeBase()
    session = SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q")

    await agent_factory.create_linsight_agent(session, [kb, _FakeWeb()], citation_scope=scope)

    tools = captured["tools"]
    assert kb.citation_scope is scope
    web_tools = [t for t in tools if isinstance(t, _LinsightWebCitationWrapper)]
    assert web_tools and web_tools[0].scope is scope

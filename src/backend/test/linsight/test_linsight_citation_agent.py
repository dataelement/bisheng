"""F047: wrap web_search and inject citation.yaml into linsight prompts."""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.citation.domain.services.citation_prompt_helper import (
    ensure_citation_rules,
    prompt_has_citation_rules,
)
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _annotate_web_search_output,
    _build_researcher_prompt,
    _build_researcher_subagent,
    _is_web_search_tool,
    _with_citation_rules,
    _wrap_linsight_web_citation_tools,
)


class _WebIn(BaseModel):
    query: str = Field(default="")


class _FakeWeb(BaseTool):
    name: str = "web_search"
    description: str = "search the web"
    args_schema: type[BaseModel] = _WebIn
    payload: str = "[]"

    def _run(self, query: str = "") -> str:
        return self.payload

    async def _arun(self, query: str = "") -> str:
        return self.payload


class _FakeOther(BaseTool):
    name: str = "not_web"
    description: str = "other"
    args_schema: type[BaseModel] = _WebIn

    def _run(self, query: str = "") -> str:
        return "other"

    async def _arun(self, query: str = "") -> str:
        return "other"


@pytest.fixture
def cache_web(monkeypatch: pytest.MonkeyPatch):
    cached = {}

    async def fake_cache(items):
        cached["items"] = items
        return items

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items",
        fake_cache,
    )
    return cached


async def test_annotate_web_search_output_adds_citation_key(cache_web):
    raw = json.dumps(
        [{"url": "https://example.com/pm25", "title": "PM2.5", "snippet": "28.6", "source": "example.com"}]
    )
    annotated = await _annotate_web_search_output(raw)
    rows = json.loads(annotated)
    assert rows[0]["citation_key"].startswith("websearch_")
    assert cache_web["items"]
    assert cache_web["items"][0].sourcePayload.url == "https://example.com/pm25"


async def test_annotate_web_search_output_passthrough_on_bad_payload(cache_web):
    assert await _annotate_web_search_output("not-json") == "not-json"
    assert await _annotate_web_search_output(json.dumps({"状态": "成功"})) == json.dumps({"状态": "成功"})
    assert "items" not in cache_web


async def test_wrap_web_search_tool_registers_citations(cache_web):
    inner = _FakeWeb(
        payload=json.dumps([{"url": "https://example.com/a", "title": "A", "snippet": "s", "source": "ex"}])
    )
    wrapped = _wrap_linsight_web_citation_tools([inner, _FakeOther()])
    assert wrapped[1].name == "not_web"
    assert wrapped[0].name == "web_search"
    assert wrapped[0] is not inner

    result = await wrapped[0].ainvoke({"query": "pm2.5"})
    assert "citation_key" in result
    assert cache_web["items"]


async def test_wrap_web_search_annotate_failure_returns_bare(monkeypatch: pytest.MonkeyPatch):
    async def boom(_output):
        raise RuntimeError("annotate exploded")

    monkeypatch.setattr(agent_factory, "_annotate_web_search_output", boom)
    inner = _FakeWeb(payload='[{"url":"https://example.com/a"}]')
    wrapped = _wrap_linsight_web_citation_tools([inner])[0]
    result = await wrapped.ainvoke({"query": "q"})
    assert result == inner.payload


def test_is_web_search_tool_matches_name_or_tool_name():
    assert _is_web_search_tool(_FakeWeb())
    assert _is_web_search_tool(type("T", (), {"name": "other", "tool_name": "web_search"})())
    assert not _is_web_search_tool(_FakeOther())


def test_citation_rules_only_when_kb_or_web():
    bare = "system prompt"
    with_rules = _with_citation_rules(bare, True)
    without = _with_citation_rules(bare, False)
    assert prompt_has_citation_rules(with_rules)
    assert not prompt_has_citation_rules(without)
    # idempotent
    assert _with_citation_rules(with_rules, True) == with_rules


def test_citation_rules_require_real_pua_and_cover_written_files():
    """Task-mode preview reads output/*.md; the shared rules must teach real
    U+E200 markers for written files too, and never show the escaped form."""
    rules = _with_citation_rules("system prompt", True)
    assert chr(0xE200) in rules
    assert chr(0xE201) in rules
    assert chr(0xE202) in rules
    assert "任何文件" in rules
    # The six-character form is named only as a prohibition, never spelled out.
    assert "反斜杠" in rules
    assert "\\" not in rules
    assert _with_citation_rules(rules, True) == rules


def test_with_citation_rules_delegates_to_the_shared_backstop():
    """Linsight teaches exactly the same rules as daily chat / knowledge space /
    channel — no task-mode-only paragraph any more."""
    prompt = "system prompt"
    assert _with_citation_rules(prompt, True) == ensure_citation_rules(prompt)
    assert "File Output" not in _with_citation_rules(prompt, True)


def test_researcher_prompt_requires_last_message_handoff_when_citable():
    kb = _build_researcher_prompt(True)
    web = _build_researcher_prompt(False, has_web_search=True)
    none = _build_researcher_prompt(False)
    assert "chunk_id" in kb
    assert "citation_key" in kb
    assert "最后一条" in kb
    assert "citation_key" in web
    assert "citation_key" not in none
    assert "<chunk_id>" not in none
    assert "__CITATION_HANDOFF_LINE__" not in kb
    assert "__CITATION_HANDOFF_LINE__" not in none


def test_researcher_subagent_injects_rules_for_web_search():
    spec = _build_researcher_subagent([_FakeWeb()])
    assert prompt_has_citation_rules(spec["system_prompt"])
    spec_plain = _build_researcher_subagent([_FakeOther()])
    assert not prompt_has_citation_rules(spec_plain["system_prompt"])

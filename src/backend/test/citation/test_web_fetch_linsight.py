"""Task mode: web_fetch is a citable web tool (F085)."""

import json
from typing import Any

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.citation.domain.services import citation_handle_service as handle_svc
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.agent_factory import (
    _build_researcher_subagent,
    _is_web_citation_tool,
    _wrap_linsight_web_citation_tools,
)
from test.linsight.test_linsight_knowledge_handles import _fake_assign, _Scope


class _UrlInput(BaseModel):
    url: str = Field(description="url")


class _FakeFetchTool(BaseTool):
    name: str = "web_fetch"
    description: str = "fake fetch"
    args_schema: type[BaseModel] = _UrlInput
    fail: bool = False

    def _run(self, url: str, **kwargs: Any) -> str:
        if self.fail:
            raise RuntimeError("engine exploded")
        return json.dumps({"title": "Page", "url": url, "source": "example.com", "content": "Body text."})


@pytest.fixture(autouse=True)
def cache_web(monkeypatch: pytest.MonkeyPatch):
    async def fake_cache(items):
        return items

    monkeypatch.setattr(
        "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items", fake_cache
    )


def _wrap(tool: BaseTool, scope=None) -> BaseTool:
    return _wrap_linsight_web_citation_tools([tool], scope=scope)[0]


def test_web_fetch_counts_as_a_web_citation_tool():
    assert _is_web_citation_tool(_FakeFetchTool())


async def test_fetch_result_carries_key_and_is_recorded():
    scope = _Scope(enabled=False)
    wrapped = _wrap(_FakeFetchTool(), scope)

    page = json.loads(await wrapped.ainvoke({"url": "https://example.com/l"}))

    assert page["citation_key"].startswith("websearch_")
    assert [item.key for item in scope.seen] == [page["citation_key"]]


async def test_fetch_result_shows_a_handle(monkeypatch):
    monkeypatch.setattr(handle_svc, "assign_handles", _fake_assign({0: "S5"}))
    wrapped = _wrap(_FakeFetchTool(), _Scope())

    page = json.loads(await wrapped.ainvoke({"url": "https://example.com/l"}))

    assert page["ref"] == "S5"
    assert "citation_key" not in page


async def test_fetch_failure_is_returned_as_text():
    wrapped = _wrap(_FakeFetchTool(fail=True), _Scope())

    output = await wrapped.ainvoke({"url": "https://example.com/l"})

    assert output.startswith("网页读取失败")


def test_researcher_gets_citation_rules_with_only_web_fetch():
    researcher = _build_researcher_subagent([_FakeFetchTool()], citation_handles=False)

    assert "citation_key" in researcher["system_prompt"]
    assert agent_factory._with_citation_rules("p", True) != "p"

"""Assistant and workflow citation wrappers pass the URL to web_fetch and cite the page (F085)."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.api.services.assistant_agent import AssistantAgent, AssistantCitationToolWrapper
from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.workflow.common.citation_keys import WORKFLOW_CITATION_REGISTRY_ITEMS_KEY
from bisheng.workflow.nodes.agent.agent import AgentNode, WorkflowCitationToolWrapper
from bisheng.workflow.nodes.tool.tool import ToolNode


class _UrlInput(BaseModel):
    url: str = Field(description="url")


class _FakeFetchTool(BaseTool):
    name: str = "web_fetch"
    description: str = "fake fetch"
    args_schema: type[BaseModel] = _UrlInput
    seen_urls: list[str] = Field(default_factory=list)

    def _run(self, url: str, **kwargs: Any) -> str:
        self.seen_urls.append(url)
        return json.dumps({"title": "Page", "url": url, "source": "example.com", "content": "Body text."})


class _QueryInput(BaseModel):
    query: str = Field(description="query")


class _FakeSearchTool(BaseTool):
    name: str = "web_search"
    description: str = "fake search"
    args_schema: type[BaseModel] = _QueryInput

    def _run(self, query: str, **kwargs: Any) -> str:
        return json.dumps([{"title": "Hit", "url": "https://example.com/hit", "snippet": query}])


@pytest.fixture(autouse=True)
def _no_redis():
    with (
        patch("bisheng.api.services.assistant_agent.cache_citation_registry_items_sync"),
        patch("bisheng.api.services.assistant_agent.cache_citation_registry_items"),
        patch("bisheng.workflow.nodes.agent.agent.cache_citation_registry_items_sync"),
        patch("bisheng.workflow.nodes.agent.agent.cache_citation_registry_items"),
        patch("bisheng.workflow.nodes.tool.tool.cache_citation_registry_items_sync"),
    ):
        yield


def _assistant_wrapper(tool: BaseTool) -> tuple[BaseTool, CitationRegistryCollector]:
    collector = CitationRegistryCollector()
    agent = SimpleNamespace(citation_registry_collector=collector)
    return AssistantAgent.wrap_citation_tool(agent, tool), collector


def test_assistant_wraps_web_fetch_and_passes_the_url():
    inner = _FakeFetchTool()
    wrapper, collector = _assistant_wrapper(inner)

    assert isinstance(wrapper, AssistantCitationToolWrapper)
    page = json.loads(wrapper.invoke({"url": "https://example.com/p"}))

    assert inner.seen_urls == ["https://example.com/p"]
    assert page["citation_key"].startswith("websearch_")
    assert [item.key for item in collector.items] == [page["citation_key"]]


async def test_assistant_async_fetch_reuses_the_source_for_the_same_url():
    wrapper, collector = _assistant_wrapper(_FakeFetchTool())

    first = json.loads(await wrapper.ainvoke({"url": "https://example.com/p"}))
    second = json.loads(await wrapper.ainvoke({"url": "https://example.com/p/"}))

    assert first["citation_key"] == second["citation_key"]
    assert [item.key for item in collector.items] == [first["citation_key"]]


def test_assistant_web_search_keeps_list_annotation():
    wrapper, collector = _assistant_wrapper(_FakeSearchTool())

    results = json.loads(wrapper.invoke({"query": "q"}))

    assert results[0]["citation_key"].startswith("websearch_")
    assert len(collector.items) == 1


def test_workflow_agent_wraps_web_fetch_and_passes_the_url():
    inner = _FakeFetchTool()
    wrapper = AgentNode._wrap_citation_tool(inner)

    assert isinstance(wrapper, WorkflowCitationToolWrapper)
    page = json.loads(wrapper.invoke({"url": "https://example.com/w"}))

    assert inner.seen_urls == ["https://example.com/w"]
    assert [item.key for item in wrapper.citation_registry_items] == [page["citation_key"]]


async def test_workflow_agent_async_web_fetch():
    inner = _FakeFetchTool()
    wrapper = AgentNode._wrap_citation_tool(inner)

    page = json.loads(await wrapper.ainvoke({"url": "https://example.com/w"}))

    assert page["citation_key"].startswith("websearch_")


def test_workflow_tool_node_annotates_web_fetch_output():
    node = ToolNode.__new__(ToolNode)
    node.id = "tool_1"
    node._tool = _FakeFetchTool()
    node._tool_info = SimpleNamespace(tool_key="web_fetch", id=40)
    node.graph_state = MagicMock()
    node.parse_tool_input = lambda: {"url": "https://example.com/node"}
    node._init_tool = lambda: None

    output = json.loads(node._run("u1")["output"])

    assert output["citation_key"].startswith("websearch_")
    calls = {call.args[1]: call.args[2] for call in node.graph_state.set_variable.call_args_list}
    assert [item.key for item in calls[WORKFLOW_CITATION_REGISTRY_ITEMS_KEY]] == [output["citation_key"]]

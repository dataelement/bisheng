"""Daily chat: web_fetch gets the citation wrapper, a short handle and a web tool card (F085)."""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.citation.domain.services import citation_handle_service as svc
from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.workstation.domain.services import chat_service
from bisheng.workstation.domain.services.chat_service import (
    DailyChatCitationToolWrapper,
    _build_tool_meta,
    _wrap_daily_chat_citation_tool,
)
from test.citation.test_daily_citation_scope import FakeRedis


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


@pytest.fixture(autouse=True)
def _no_cache():
    with (
        patch.object(chat_service, "cache_citation_registry_items_sync"),
        patch.object(chat_service, "cache_citation_registry_items"),
    ):
        yield


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRedis()
    monkeypatch.setattr(svc, "get_redis_client", AsyncMock(return_value=fake))
    return fake


def _wrap(tool: BaseTool, scope: DailyCitationScope | None = None):
    collector = CitationRegistryCollector()
    return _wrap_daily_chat_citation_tool(tool, collector, citation_scope=scope), collector


def test_sync_call_passes_url_and_drops_the_key_under_handles():
    inner = _FakeFetchTool()
    wrapper, collector = _wrap(inner, DailyCitationScope("chat-1"))

    assert isinstance(wrapper, DailyChatCitationToolWrapper)
    page = json.loads(wrapper.invoke({"url": "https://example.com/d"}))

    assert inner.seen_urls == ["https://example.com/d"]
    assert "citation_key" not in page
    assert len(collector.items) == 1


async def test_async_call_shows_a_short_handle(redis):
    wrapper, collector = _wrap(_FakeFetchTool(), DailyCitationScope("chat-2"))

    first = json.loads(await wrapper.ainvoke({"url": "https://example.com/d"}))
    second = json.loads(await wrapper.ainvoke({"url": "https://example.com/d"}))

    assert first["ref"] == "S1"
    assert second["ref"] == "S1"
    assert "citation_key" not in first
    assert len(collector.items) == 1


async def test_async_call_without_scope_keeps_the_key():
    wrapper, _ = _wrap(_FakeFetchTool())

    page = json.loads(await wrapper.ainvoke({"url": "https://example.com/d"}))

    assert page["citation_key"].startswith("websearch_")


def test_tool_meta_marks_web_fetch_as_web():
    assert _build_tool_meta(_FakeFetchTool()) == {"display_name": "web_fetch", "tool_type": "web"}

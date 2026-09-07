"""Daily-chat image-view wiring (F061 T013).

Covers AC: AC-02, AC-03, AC-10, AC-18
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector
from bisheng.common.image_view import IMAGE_VIEW_PROMPT_RULES, ImageRegistry, annotate
from bisheng.workstation.domain.services.chat_service import (
    DailyChatCitationToolWrapper,
    VisionToolBindWrapper,
    _prepare_tools,
)


@lc_tool
def _dummy_kb(query: str) -> str:
    """Dummy knowledge tool."""
    return "[]"


@pytest.fixture(autouse=True)
def _stub_format_retrieved_chunk(monkeypatch):
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service.knowledge_imp.KnowledgeUtils.format_retrieved_chunk",
        staticmethod(lambda doc, kb_name="": getattr(doc, "page_content", "")),
        raising=False,
    )


def _wrapper(registry: ImageRegistry | None) -> DailyChatCitationToolWrapper:
    wrapped = DailyChatCitationToolWrapper.wrap(
        _dummy_kb,
        CitationRegistryCollector(),
        image_registry=registry,
    )
    assert isinstance(wrapped, DailyChatCitationToolWrapper)
    return wrapped


def test_dump_knowledge_chunks_annotates_after_format():
    registry = ImageRegistry()
    doc = Document(
        page_content="see ![chart](/bisheng/knowledge/images/1/2/c.png)",
        metadata={"document_name": "f.md", "knowledge_id": "1"},
    )
    text = _wrapper(registry)._dump_knowledge_chunks([doc, doc])
    assert "![chart](/bisheng/knowledge/images/1/2/c.png)⟦img#1⟧" in text
    assert text.count("⟦img#1⟧") == 2
    assert "⟦img#2⟧" not in text
    assert registry.get("img#1") == {"url": "/bisheng/knowledge/images/1/2/c.png"}


def test_dump_knowledge_chunks_skips_annotate_without_registry():
    doc = Document(
        page_content="see ![chart](/bisheng/knowledge/images/1/2/c.png)",
        metadata={"document_name": "f.md", "knowledge_id": "1"},
    )
    text = _wrapper(None)._dump_knowledge_chunks([doc])
    assert "⟦img#" not in text
    assert "![chart](/bisheng/knowledge/images/1/2/c.png)" in text


@pytest.mark.asyncio
async def test_prepare_tools_does_not_include_view_image(monkeypatch):
    @lc_tool
    def web_search(query: str) -> str:
        """Web search."""
        return "[]"

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service._build_web_search_tool",
        AsyncMock(return_value=(web_search, None)),
    )
    kb = SimpleNamespace(name="search_knowledge_bases")
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service._build_knowledge_search_tool",
        AsyncMock(return_value=kb),
    )

    tools, _ = await _prepare_tools(
        tool_payloads=[{"type": "tool", "tool_key": "web_search", "id": 1}],
        login_user=MagicMock(),
        ws_config=SimpleNamespace(maxTokens=1000),
        citation_collector=CitationRegistryCollector(),
        knowledge_bases_info=[{"id": 1, "name": "kb"}],
        image_registry=ImageRegistry(),
    )
    names = [t.name for t in tools]
    assert "view_image" not in names
    assert "web_search" in names
    assert "search_knowledge_bases" in names


class _NamedTool:
    def __init__(self, name: str):
        self.name = name


class _RecordingLLM:
    def __init__(self):
        self.bind_calls: list[list[str]] = []
        self.stream_messages: list[list] = []

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append([getattr(tool, "name", "") for tool in tools])
        return _Bound(self)


class _Bound:
    def __init__(self, parent: _RecordingLLM):
        self.parent = parent

    async def ainvoke(self, messages, config=None, **kwargs):
        self.parent.stream_messages.append(list(messages))
        return AIMessage(content="ok")

    def invoke(self, messages, config=None, **kwargs):
        self.parent.stream_messages.append(list(messages))
        return AIMessage(content="ok")


@pytest.mark.asyncio
async def test_vision_wrapper_empty_registry_binds_only_base_tools():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    result = await runnable.ainvoke([HumanMessage(content="hi")])
    assert result.content == "ok"
    assert llm.bind_calls == [["web_search"]]
    joined = "".join(str(m.content) for m in llm.stream_messages[0])
    assert IMAGE_VIEW_PROMPT_RULES not in joined
    assert "view_image" not in joined


@pytest.mark.asyncio
async def test_vision_wrapper_nonempty_registry_binds_view_image_and_rules():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    annotate("![chart](/bisheng/knowledge/images/1/2/c.png)", registry)
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    await runnable.ainvoke([SystemMessage(content="base"), HumanMessage(content="trend")])
    assert llm.bind_calls == [["web_search", "view_image"]]
    joined = "".join(str(m.content) for m in llm.stream_messages[0])
    assert IMAGE_VIEW_PROMPT_RULES in joined


@pytest.mark.asyncio
async def test_vision_wrapper_relocates_tool_images_to_human():
    llm = _RecordingLLM()
    registry = ImageRegistry()
    wrapper = VisionToolBindWrapper(llm, registry, [_NamedTool("web_search")])
    runnable = wrapper({}, None)
    await runnable.ainvoke(
        [
            HumanMessage(content="q"),
            ToolMessage(
                content=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,aaa"}}],
                tool_call_id="c1",
            ),
        ]
    )
    messages = llm.stream_messages[0]
    assert not any(isinstance(m, ToolMessage) and isinstance(m.content, list) for m in messages)
    humans = [m for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, list)]
    assert humans
    assert any(isinstance(block, dict) and block.get("type") == "image_url" for block in humans[-1].content)

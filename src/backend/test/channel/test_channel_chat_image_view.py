"""Channel article image-view wiring (F061 T011).

Covers AC: AC-02, AC-03, AC-12, AC-14
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from bisheng.channel.domain.services.channel_chat_service import ChannelChatService

_ENDPOINT = Path(__file__).resolve().parents[2] / "bisheng" / "channel" / "api" / "endpoints" / "channel_chat.py"
_IMG = "![chart](https://intel.example/chart.png)"
_DEFAULT_USER_PROMPT = "{article_content}\n{question}"


def test_endpoint_does_not_orchestrate_vision_or_llm_stream():
    text = _ENDPOINT.read_text(encoding="utf-8")
    assert "run_vision_tool_loop" not in text
    assert "ImageRegistry" not in text
    assert "bishengllm.astream" not in text
    assert "ensure_article_sensitive_view_allowed" in text


def test_apply_image_anchors_when_visual_and_markdown():
    text, registry = ChannelChatService._apply_image_anchors(f"body {_IMG}", visual=True)
    assert f"{_IMG}⟦img#1⟧" in text
    assert registry.get("img#1") == {"url": "https://intel.example/chart.png"}


def test_apply_image_anchors_skipped_when_not_visual():
    raw = f"body {_IMG}"
    text, registry = ChannelChatService._apply_image_anchors(raw, visual=False)
    assert text == raw
    assert "⟦img#" not in text
    assert len(registry) == 0


def test_apply_image_anchors_noop_without_markdown_image():
    raw = "plain article <img src='https://intel.example/x.png'>"
    text, registry = ChannelChatService._apply_image_anchors(raw, visual=True)
    assert text == raw
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_resolve_workbench_visual_reads_wsmodel(monkeypatch):
    monkeypatch.setattr(
        "bisheng.channel.domain.services.channel_chat_service.LLMService.get_workbench_llm",
        AsyncMock(
            return_value=SimpleNamespace(
                models=[SimpleNamespace(id="11", visual=True), SimpleNamespace(id="12", visual=False)]
            )
        ),
    )
    assert await ChannelChatService._resolve_workbench_visual(11) is True
    assert await ChannelChatService._resolve_workbench_visual(12) is False
    assert await ChannelChatService._resolve_workbench_visual(99) is False


@pytest.mark.asyncio
async def test_stream_uses_vision_loop_when_visual_and_images(monkeypatch):
    llm = object()
    loop_calls: list[tuple] = []

    async def fake_loop(model, messages, registry, *, visual):
        loop_calls.append((visual, len(registry), "".join(str(m.content) for m in messages)))
        yield AIMessage(content="answer with ![chart](https://intel.example/chart.png)")

    monkeypatch.setattr(
        "bisheng.channel.domain.services.channel_chat_service.run_vision_tool_loop",
        fake_loop,
    )
    monkeypatch.setattr(ChannelChatService, "_resolve_workbench_visual", AsyncMock(return_value=True))

    events = [
        event
        async for event in ChannelChatService.stream_article_reply(
            llm=llm,
            article_content=f"intro {_IMG} tail",
            question="what trend",
            system_prompt="sys",
            user_prompt_template=_DEFAULT_USER_PROMPT,
            history_messages=[],
            model_id=11,
            max_chunk_size=15000,
        )
    ]

    assert loop_calls
    visual, registry_len, joined = loop_calls[0]
    assert visual is True
    assert registry_len == 1
    assert "⟦img#1⟧" in joined
    assert events and events[0].content.startswith("answer")


@pytest.mark.asyncio
async def test_stream_does_not_annotate_when_visual_false(monkeypatch):
    loop_calls: list[tuple] = []

    async def fake_loop(model, messages, registry, *, visual):
        loop_calls.append((visual, len(registry), "".join(str(m.content) for m in messages)))
        yield AIMessage(content="ok")

    monkeypatch.setattr(
        "bisheng.channel.domain.services.channel_chat_service.run_vision_tool_loop",
        fake_loop,
    )
    monkeypatch.setattr(ChannelChatService, "_resolve_workbench_visual", AsyncMock(return_value=False))

    async for _ in ChannelChatService.stream_article_reply(
        llm=object(),
        article_content=f"intro {_IMG}",
        question="q",
        system_prompt="sys",
        user_prompt_template=_DEFAULT_USER_PROMPT,
        history_messages=[],
        model_id=11,
        max_chunk_size=15000,
    ):
        pass

    visual, registry_len, joined = loop_calls[0]
    assert visual is False
    assert registry_len == 0
    assert "⟦img#" not in joined


@pytest.mark.asyncio
async def test_stream_does_not_annotate_without_markdown_image(monkeypatch):
    loop_calls: list[tuple] = []

    async def fake_loop(model, messages, registry, *, visual):
        loop_calls.append((visual, len(registry), "".join(str(m.content) for m in messages)))
        yield AIMessage(content="ok")

    monkeypatch.setattr(
        "bisheng.channel.domain.services.channel_chat_service.run_vision_tool_loop",
        fake_loop,
    )
    monkeypatch.setattr(ChannelChatService, "_resolve_workbench_visual", AsyncMock(return_value=True))

    async for _ in ChannelChatService.stream_article_reply(
        llm=object(),
        article_content="plain article no picture",
        question="q",
        system_prompt="sys",
        user_prompt_template=_DEFAULT_USER_PROMPT,
        history_messages=[],
        model_id=11,
        max_chunk_size=15000,
    ):
        pass

    visual, registry_len, joined = loop_calls[0]
    assert visual is True
    assert registry_len == 0
    assert "⟦img#" not in joined


class _FakeLLM:
    def __init__(self, first: AIMessage, second: AIMessage):
        self.first = first
        self.second = second
        self._bound = False

    def bind_tools(self, tools, **kwargs):
        bound = _FakeLLM(self.first, self.second)
        bound._bound = True
        bound._parent = self
        return bound

    async def astream(self, messages, **kwargs):
        if self._bound:
            yield self.first
            return
        yield self.second


@pytest.mark.asyncio
async def test_stream_does_not_yield_first_round_tool_tokens(monkeypatch):
    fetch = AsyncMock(
        return_value=type("R", (), {"ok": True, "data_uri": "data:image/png;base64,aaa", "error": None})()
    )
    monkeypatch.setattr("bisheng.common.image_view.tool.fetch_and_encode", fetch)
    monkeypatch.setattr(ChannelChatService, "_resolve_workbench_visual", AsyncMock(return_value=True))

    llm = _FakeLLM(
        first=AIMessage(
            content="calling tool",
            tool_calls=[
                {
                    "name": "view_image",
                    "args": {"image_ids": ["img#1"], "quality": "standard"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        second=AIMessage(content="final from pixels"),
    )

    texts = [
        event.content
        async for event in ChannelChatService.stream_article_reply(
            llm=llm,
            article_content=f"see {_IMG}",
            question="what trend",
            system_prompt="sys",
            user_prompt_template=_DEFAULT_USER_PROMPT,
            history_messages=[],
            model_id=11,
            max_chunk_size=15000,
        )
    ]

    joined = "".join(texts)
    assert "calling tool" not in joined
    assert "final from pixels" in joined
    fetch.assert_awaited()

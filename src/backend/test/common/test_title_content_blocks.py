"""Conversation titles accept Responses content blocks without exposing reasoning."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from bisheng.common.utils import title_generator


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "content, expected",
    [
        ("  Travel plan  ", "Travel plan"),
        (
            [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Private thought"}]},
                {"type": "text", "text": "  Travel "},
                {"type": "text", "text": "plan  "},
            ],
            "Travel plan",
        ),
        ([{"type": "reasoning", "summary": []}], title_generator.DEFAULT_TITLE),
    ],
)
async def test_title_extracts_only_visible_text(monkeypatch, asynchronous, content, expected):
    loader = SimpleNamespace(render_prompt=lambda *_a, **_k: SimpleNamespace(prompt="Name this conversation"))
    monkeypatch.setattr(title_generator, "get_prompt_manager", AsyncMock(return_value=loader))
    monkeypatch.setattr(title_generator, "get_prompt_manager_sync", lambda: loader)
    response = AIMessage(content=content)
    llm = SimpleNamespace(invoke=lambda _messages: response, ainvoke=AsyncMock(return_value=response))

    if asynchronous:
        result = await title_generator.generate_conversation_title_async("Travel", llm)
    else:
        result = title_generator.generate_conversation_title_sync("Travel", llm)

    assert result == expected

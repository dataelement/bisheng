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
        ([{"type": "reasoning", "summary": []}], "Travel"),
        ("<think>Private thought</think>Travel plan", "Travel plan"),
        ("<think>Unfinished private thought", "Travel"),
        ("Travel plan\nExtra explanation", "Travel plan"),
        ("T" * 300, "T" * 50),
        ("", "Travel"),
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


async def test_title_timeout_uses_question(monkeypatch):
    import asyncio

    loader = SimpleNamespace(render_prompt=lambda *_a, **_k: SimpleNamespace(prompt="Name this conversation"))
    monkeypatch.setattr(title_generator, "get_prompt_manager", AsyncMock(return_value=loader))
    monkeypatch.setattr(title_generator, "TITLE_GENERATION_TIMEOUT_S", 0.01, raising=False)

    async def slow_model(_messages):
        await asyncio.Event().wait()

    assert (
        await title_generator.generate_conversation_title_async(
            "Summarize the document", SimpleNamespace(ainvoke=slow_model)
        )
        == "Summarize the document"
    )


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_title_provider_failure_uses_question(monkeypatch, asynchronous):
    loader = SimpleNamespace(render_prompt=lambda *_a, **_k: SimpleNamespace(prompt="Name this conversation"))
    monkeypatch.setattr(title_generator, "get_prompt_manager", AsyncMock(return_value=loader))
    monkeypatch.setattr(title_generator, "get_prompt_manager_sync", lambda: loader)

    def fail(_messages):
        raise RuntimeError("provider unavailable")

    llm = SimpleNamespace(invoke=fail, ainvoke=AsyncMock(side_effect=RuntimeError("provider unavailable")))
    if asynchronous:
        result = await title_generator.generate_conversation_title_async("Travel", llm)
    else:
        result = title_generator.generate_conversation_title_sync("Travel", llm)
    assert result == "Travel"

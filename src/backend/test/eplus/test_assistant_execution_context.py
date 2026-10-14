"""Assistant input compatibility and explicit E+ execution context."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.assistant.domain.schemas.execution import (
    AssistantEntryPoint,
    AssistantExecutionContext,
    AssistantRobotScope,
)
from bisheng.database.models.assistant import Assistant


class CharacterEncoder:
    def encode(self, value: str) -> list[str]:
        return list(value)


def _assistant(*, max_token: int = 32000) -> Assistant:
    return Assistant(
        id="assistant-1",
        name="Robot assistant",
        tenant_id=73,
        user_id=9,
        model_name="model-1",
        max_token=max_token,
    )


def _context(*, content, cancellation_check=None) -> AssistantExecutionContext:
    return AssistantExecutionContext(
        entry_point=AssistantEntryPoint.EPLUS,
        user_id=101,
        external_user_id="cofco-user-101",
        content=content,
        robot_scope=AssistantRobotScope(
            bot_config_id=7,
            space_ids=(10, 20),
            scope_version=3,
        ),
        cancellation_check=cancellation_check,
    )


def test_legacy_string_input_is_preserved_exactly() -> None:
    agent = AssistantAgent(_assistant(), "chat-1", invoke_user_id=101)
    query = "  keep whitespace\n和原始字节  "

    inputs = agent.build_input_messages(query=query, chat_history=None, context=None)

    assert len(inputs) == 1
    assert isinstance(inputs[0], HumanMessage)
    assert inputs[0].content == query
    assert inputs[0].content.encode("utf-8") == query.encode("utf-8")


def test_ordered_multimodal_blocks_form_one_human_message_without_mutating_assistant() -> None:
    assistant = _assistant()
    before = deepcopy(assistant.model_dump())
    blocks = [
        {"type": "text", "text": "before"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": "after"},
    ]
    agent = AssistantAgent(assistant, "chat-1", invoke_user_id=101)

    inputs = agent.build_input_messages(
        query="fallback",
        chat_history=None,
        context=_context(content=blocks),
    )

    assert len(inputs) == 1
    assert inputs[0].content == blocks
    assert assistant.model_dump() == before


async def test_token_trimming_supports_text_and_content_blocks(monkeypatch) -> None:
    agent = AssistantAgent(_assistant(max_token=70), "chat-1", invoke_user_id=101)
    monkeypatch.setattr(agent, "cl100k_base", lambda: CharacterEncoder())
    messages = [
        HumanMessage(content="old" * 30),
        AIMessage(content="answer"),
        HumanMessage(
            content=[
                {"type": "text", "text": "new"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]
        ),
    ]

    trimmed = await agent.trim_messages(messages)

    assert messages[0] not in trimmed
    assert trimmed[-1].content == messages[-1].content


async def test_cancellation_stops_before_agent_invocation() -> None:
    agent = AssistantAgent(_assistant(), "chat-1", invoke_user_id=101)
    agent.current_agent_executor = "function call"
    agent.agent = type("FakeAgent", (), {"ainvoke": AsyncMock(return_value={"messages": []})})()
    context = _context(content="question", cancellation_check=lambda: True)

    with pytest.raises(asyncio.CancelledError):
        await agent.run("fallback", context=context)

    agent.agent.ainvoke.assert_not_awaited()


async def test_stream_checks_cancellation_between_chunks() -> None:
    checks = iter((False, False, True))

    class FakeAgent:
        async def astream(self, *args, **kwargs):
            yield HumanMessage(content="first"), {}
            yield HumanMessage(content="second"), {}

    agent = AssistantAgent(_assistant(), "chat-1", invoke_user_id=101)
    agent.current_agent_executor = "function call"
    agent.agent = FakeAgent()
    context = _context(content="question", cancellation_check=lambda: next(checks))
    stream = agent.astream("fallback", context=context)

    first = await anext(stream)
    assert first[0].content == "first"
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

# ruff: noqa: RUF001 - the admin prompt under test deliberately carries full-width CJK punctuation
"""Daily-chat citation backstop: the system prompt handed to the model.

``_agent_stream_chat_completion`` builds the daily-chat system prompt as
``ensure_citation_rules(<admin prompt with {cur_date} replaced>)``. Two edges of
that contract are pinned here by capturing the exact message list the model
receives on the no-tools branch (``bisheng_llm.astream``):

1. An empty admin prompt still yields a SystemMessage carrying exactly the
   citation rules — citations keep working when the admin blanks the prompt.
2. An admin prompt that already teaches the marker with the six-character
   literal ``\\ue200`` (not the real U+E200 char) is passed through untouched —
   placeholder substituted, rules NOT appended a second time.

The fixture mirrors ``test_stream_interrupt_persist.stream_env`` but its fake
LLM records the ``messages`` argument instead of ignoring it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.citation.domain.services.citation_prompt_helper import CITATION_PROMPT_RULES
from bisheng.workstation.domain.services import chat_service

# Six ASCII characters (backslash, u, e, 2, 0, 0) — the literal spelling that
# ``prompt_has_citation_rules`` accepts in place of the real U+E200 char.
_LITERAL_START_MARKER = chr(92) + "ue200"
_ADMIN_PROMPT_WITH_LITERAL_MARKER = (
    "自定义提示词。当前时间{cur_date}。\n- `" + _LITERAL_START_MARKER + "`：引用开始标记"
)


class _Chunk:
    """Minimal stand-in for a LangChain streaming chunk."""

    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


def _data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-09-09T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text="创盈芯投资可行性分析",
    )


@pytest.fixture
def citation_env(monkeypatch: pytest.MonkeyPatch):
    """Patch everything around the generator, leaving the prompt assembly real.

    Returns a handle exposing the mutable workstation config (set
    ``systemPrompt`` before driving the stream) and the message lists the fake
    model received, one entry per ``astream`` call.
    """
    received: list[list] = []

    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")

    class _LLM:
        async def astream(self, messages):
            received.append(list(messages))
            yield _Chunk("答案")

    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(return_value=(ws_config, conversation, message, _LLM(), model_info, False)),
    )
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        "get_chat_history",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        chat_service.DepartmentFlowService,
        "resolve_limit_and_dept",
        AsyncMock(return_value=(0, None)),
    )
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations_sync", MagicMock(return_value=None))

    def _record(row):
        row.id = 901
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))

    return SimpleNamespace(ws_config=ws_config, received=received)


async def _drive_no_tools_stream() -> None:
    """Run the daily-chat SSE generator to completion so ``astream`` is invoked."""
    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())
    async for _chunk in response.body_iterator:
        pass


async def test_empty_admin_prompt_yields_rules_only_system_message(citation_env):
    """systemPrompt="" → messages[0] is a SystemMessage equal to CITATION_PROMPT_RULES."""
    # Guard the assertion's meaning: if the prompt file failed to load, the
    # constant is an error string and the equality below would pass vacuously.
    assert chr(0xE200) in CITATION_PROMPT_RULES

    citation_env.ws_config.systemPrompt = ""

    await _drive_no_tools_stream()

    assert len(citation_env.received) == 1
    messages = citation_env.received[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == CITATION_PROMPT_RULES
    # The user turn follows the injected system message; nothing else sneaks in.
    assert isinstance(messages[-1], HumanMessage)
    assert len(messages) == 2


async def test_admin_prompt_with_literal_marker_is_not_double_appended(citation_env):
    """A prompt spelling the marker as literal ``\\ue200`` is passed through unchanged."""
    citation_env.ws_config.systemPrompt = _ADMIN_PROMPT_WITH_LITERAL_MARKER

    await _drive_no_tools_stream()

    assert len(citation_env.received) == 1
    messages = citation_env.received[0]
    assert isinstance(messages[0], SystemMessage)
    content = messages[0].content
    assert content.startswith("自定义提示词。")
    assert "{cur_date}" not in content
    assert CITATION_PROMPT_RULES not in content
    # The admin's own marker line survives verbatim (only the date was substituted).
    assert _LITERAL_START_MARKER in content
    assert content.endswith("`：引用开始标记")

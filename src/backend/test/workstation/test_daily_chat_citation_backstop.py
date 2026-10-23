# ruff: noqa: RUF001 - the admin prompt under test deliberately carries full-width CJK punctuation
"""Daily-chat citation rules: the system prompt handed to the model (F072).

``_agent_stream_chat_completion`` builds the daily-chat system prompt as
``replace_legacy_citation_rules(<admin prompt with {cur_date} replaced>)``: the
model is taught the ``[Sn]`` handle rules and never the verbatim-id format.
Pinned here by capturing the exact message list the model receives on the
no-tools branch (``bisheng_llm.astream``):

1. An empty admin prompt yields a SystemMessage carrying exactly the daily
   handle rules — citations keep working when the admin blanks the prompt.
2. An admin prompt that teaches the old marker in its own words (no heading to
   cut) keeps its text and gets the handle rules appended, which prevail.
3. The saved legacy default section is swapped out; the date line under it
   survives.

The fixture mirrors ``test_stream_interrupt_persist.stream_env`` but its fake
LLM records the ``messages`` argument instead of ignoring it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.citation.domain.services.citation_handle_service import HANDLE_RULES_HEADER
from bisheng.citation.domain.services.daily_citation_handles import load_daily_handle_rules
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
    # Image viewing reads its model config from the DB; off for these tests.
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    # The citation handle table lives in Redis; start each turn with an empty one.
    monkeypatch.setattr(chat_service.DailyCitationScope, "load", AsyncMock(return_value=None))
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
    """systemPrompt="" → messages[0] is a SystemMessage equal to the daily handle rules."""
    rules = load_daily_handle_rules()
    # Guard the assertion's meaning: a failed prompt load yields an error string.
    assert rules.startswith(HANDLE_RULES_HEADER) and "[S3]" in rules

    citation_env.ws_config.systemPrompt = ""

    await _drive_no_tools_stream()

    assert len(citation_env.received) == 1
    messages = citation_env.received[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == rules
    # The user turn follows the injected system message; nothing else sneaks in.
    assert isinstance(messages[-1], HumanMessage)
    assert len(messages) == 2


async def test_admin_prompt_with_its_own_marker_wording_gets_handle_rules_appended(citation_env):
    """No legacy heading to cut: the admin text stays, the handle rules follow and prevail."""
    citation_env.ws_config.systemPrompt = _ADMIN_PROMPT_WITH_LITERAL_MARKER

    await _drive_no_tools_stream()

    content = citation_env.received[0][0].content
    assert content.startswith("自定义提示词。")
    assert "{cur_date}" not in content
    assert content.endswith(load_daily_handle_rules())


async def test_saved_legacy_section_is_swapped_and_date_line_kept(citation_env):
    citation_env.ws_config.systemPrompt = (
        "# 角色\n你是助手。\n\n# 引用规则\n按规则标注。\n\n## 来源 ID\n知识库结果在 `<chunk_id>` 标签中。\n\n"
        "## 标记格式\n- `" + _LITERAL_START_MARKER + "`：引用开始标记\n\n## 使用要求\n1. 放在段落末尾。\n\n"
        "## 其他信息\n当前时间：{cur_date}。"
    )

    await _drive_no_tools_stream()

    content = citation_env.received[0][0].content
    assert "<chunk_id>" not in content
    assert _LITERAL_START_MARKER not in content
    assert HANDLE_RULES_HEADER in content
    assert content.startswith("# 角色\n你是助手。")
    assert "当前时间：" in content and "{cur_date}" not in content

"""F035 Track J (TJ-5) — chat_id-dimension history injection.

In the unified model each task turn is a fresh session_version (a fresh agent
thread), so the deepagents checkpointer alone does NOT carry the prior
conversation (earlier daily turns + earlier task turns live elsewhere). Before
a fresh task turn runs, prior context is rebuilt from the conversation's
``ChatMessage`` rows (by chat_id) and injected, so the model answers with full
context (C8 ④, design §3.2).

The summary pairs each user question with its following bot answer; a trailing
unanswered question (the CURRENT turn, just written at submit) forms no pair and
is therefore excluded — no duplication of the question already seeded into the
agent input.

ChatMessageDao is patched; the unit under test is the pairing/formatting logic.
"""

from __future__ import annotations

import json

import pytest

from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.linsight.domain import utils as linsight_execute_utils


def _q(id_: int, query: str) -> ChatMessage:
    return ChatMessage(
        id=id_,
        is_bot=False,
        chat_id="chat-1",
        user_id=1,
        flow_id="",
        type="over",
        category="question",
        message=json.dumps({"query": query, "files": []}),
        tenant_id=1,
    )


def _a(id_: int, answer: str, category: str = "answer") -> ChatMessage:
    return ChatMessage(
        id=id_,
        is_bot=True,
        chat_id="chat-1",
        user_id=1,
        flow_id="",
        type="over",
        category=category,
        message=answer,
        tenant_id=1,
    )


@pytest.fixture
def patch_messages(monkeypatch: pytest.MonkeyPatch):
    rows: list[ChatMessage] = []

    async def _fake(_cls, chat_id, **kwargs):
        return list(rows)

    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", classmethod(_fake))
    return rows


async def test_summary_pairs_prior_qa_and_excludes_current_turn(patch_messages):
    """Prior completed Q/A pairs are summarized; the trailing unanswered turn is dropped."""
    patch_messages.extend(
        [
            _q(1, "问题一"),
            _a(2, "回答一"),
            _q(3, "问题二"),
            _a(4, "回答二", category="task"),  # a prior task turn counts too
            _q(5, "当前问题"),  # current turn, no answer yet
        ]
    )

    summary = await linsight_execute_utils.build_prior_conversation_summary("chat-1")

    assert "问题一" in summary and "回答一" in summary
    assert "问题二" in summary and "回答二" in summary
    assert "当前问题" not in summary


async def test_summary_empty_when_no_prior_pairs(patch_messages):
    """No prior history (only the current question) yields an empty summary."""
    patch_messages.append(_q(1, "当前问题"))

    summary = await linsight_execute_utils.build_prior_conversation_summary("chat-1")

    assert summary == ""


def test_build_agent_input_prepends_history_before_question():
    """_build_agent_input puts the prior-context block ahead of the current question."""
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    session = LinsightSessionVersion(id="SV-1", session_id="chat-1", user_id=1, question="当前问题", tenant_id=1)
    out = LinsightWorkflowTask._build_agent_input(
        session, file_list=None, history_summary="# 前情回顾\n用户：旧问\n助手：旧答"
    )

    content = out["messages"][0]["content"]
    assert "前情回顾" in content
    assert content.index("前情回顾") < content.index("当前问题")


async def test_summary_head_tail_keeps_first_turn_and_recent(patch_messages):
    """Long history: deterministic head+tail retention.

    The FIRST turn (original requirements) is ALWAYS kept so the deliverable
    never drifts from the founding ask; the budget then holds the most-recent
    turn(s); an over-budget MIDDLE turn is dropped and flagged with an elision
    marker. (Replaces the old "keep most recent, drop oldest first" contract,
    which silently dropped the user's original requirements — see fix #5.)
    """
    patch_messages.extend(
        [
            _q(1, "最初需求"),
            _a(2, "最初回答"),
            _q(3, "中间问题" + "X" * 80),
            _a(4, "中间回答" + "X" * 80),
            _q(5, "最新问题"),
            _a(6, "最新回答"),
        ]
    )

    summary = await linsight_execute_utils.build_prior_conversation_summary("chat-1", max_chars=40)

    # first turn always kept (the original ask)
    assert "最初需求" in summary and "最初回答" in summary
    # most-recent turn kept
    assert "最新问题" in summary and "最新回答" in summary
    # over-budget middle turn dropped + flagged
    assert "中间问题" not in summary
    assert "省略中间" in summary


def test_build_agent_input_joins_file_list_not_repr():
    """fix #3: file_list (a list[str]) is joined, NOT interpolated as a Python repr.

    prepare_file_list returns a single-element list holding the <uploaded_files>
    block. Interpolating the list directly would emit ``['...\\n...']`` (brackets,
    quotes, escaped newlines), mangling the pointer block the model must parse.
    """
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    block = "<uploaded_files>\n- path: /uploads/a/index.md\n  name: 年报.pdf\n</uploaded_files>"
    session = LinsightSessionVersion(id="SV-1", session_id="chat-1", user_id=1, question="问", tenant_id=1)
    out = LinsightWorkflowTask._build_agent_input(session, file_list=[block])

    content = out["messages"][0]["content"]
    assert block in content  # real newlines preserved
    assert "['" not in content and "']" not in content  # no list repr brackets/quotes
    assert "\\n" not in content  # no escaped newlines


async def test_prepare_knowledge_list_clean_format_exposes_id():
    """fix #4: each KB renders as a clean line exposing knowledge_id (no i18n garble)."""
    from types import SimpleNamespace

    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    kbs = [
        SimpleNamespace(type=KnowledgeTypeEnum.NORMAL.value, id=45, name="财报库", description="历年财报"),
        SimpleNamespace(type=KnowledgeTypeEnum.PRIVATE.value, id=7, name="某私有库", description="x"),
    ]
    lines = await LinsightWorkbenchImpl.prepare_knowledge_list(kbs)

    assert lines[0] == "- 财报库 (knowledge_id: 45): 历年财报"
    # private KB: generic name (no title leak), id still exposed, no description
    assert lines[1] == "- 个人知识库 (knowledge_id: 7)"
    # no leftover machine-translation garble
    joined = "\n".join(lines)
    assert "Stored information for" not in joined and "Personal Knowledge Base" not in joined

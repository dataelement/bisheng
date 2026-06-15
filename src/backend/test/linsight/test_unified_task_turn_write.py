"""F035 Track J (TJ-3) — task-turn double-write into the unified conversation.

When a task turn finishes, its final answer must be written as a bot
``ChatMessage`` in the same daily conversation (chat_id = session_id), marked
``category='task'`` and carrying ``extra.linsight_session_version_id`` so the
frontend can lazy-load the execution detail (C8, design §2.2). The heavy
execution detail (tasks/sop/files) stays in linsight_session_version — only the
answer text + pointer land in the conversation stream.

ChatMessageDao is patched; the unit under test is the message-shaping logic.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask


@pytest.fixture
def capture_message(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    async def _fake_ainsert_one(_cls, message: ChatMessage):
        captured["message"] = message
        return message

    monkeypatch.setattr(ChatMessageDao, "ainsert_one", classmethod(_fake_ainsert_one))
    return captured


def _session(*, svid: str = "SV-1", chat_id: str = "chat-1", answer: str = "最终答案"):
    return LinsightSessionVersion(
        id=svid,
        session_id=chat_id,
        user_id=1,
        question="帮我写周报",
        output_result={"answer": answer},
        tenant_id=1,
    )


async def test_task_turn_written_as_task_category_with_sv_pointer(capture_message):
    """The bot task turn lands as a ChatMessage(category='task') with the SV pointer."""
    await linsight_execute_utils.persist_task_turn_message(_session(svid="SV-9", chat_id="chat-7"))

    msg = capture_message["message"]
    assert msg.is_bot is True
    assert msg.chat_id == "chat-7"
    assert msg.category == "task"
    assert msg.message == "最终答案"
    assert json.loads(msg.extra)["linsight_session_version_id"] == "SV-9"


async def test_direct_answer_completion_writes_task_turn(capture_message):
    """Completing a task (direct-answer path) writes the task turn into the stream."""
    task = LinsightWorkflowTask()
    task._state_manager = AsyncMock()
    task._last_assistant_text = "你好！"

    await task._handle_direct_answer_completion(_session(svid="SV-3", chat_id="chat-3"))

    msg = capture_message["message"]
    assert msg.category == "task"
    assert msg.chat_id == "chat-3"
    assert json.loads(msg.extra)["linsight_session_version_id"] == "SV-3"


async def test_user_turn_written_as_question(capture_message):
    """The task user turn lands as a ChatMessage(category='question', is_bot=False)."""
    await linsight_execute_utils.persist_task_user_turn(
        chat_id="chat-5", user_id=1, question="帮我写周报", files=None
    )

    msg = capture_message["message"]
    assert msg.is_bot is False
    assert msg.chat_id == "chat-5"
    assert msg.category == "question"
    assert "帮我写周报" in msg.message


async def test_failed_task_turn_falls_back_to_error_message(capture_message):
    """A failed task (no answer) still writes a task turn, using the error message."""
    session = LinsightSessionVersion(
        id="SV-8", session_id="chat-8", user_id=1, question="q",
        output_result={"error_message": "执行失败"}, tenant_id=1,
    )

    await linsight_execute_utils.persist_task_turn_message(session)

    msg = capture_message["message"]
    assert msg.category == "task"
    assert "执行失败" in msg.message
    assert json.loads(msg.extra)["linsight_session_version_id"] == "SV-8"

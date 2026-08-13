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
    captured: dict = {"existing": []}

    async def _fake_ainsert_one(_cls, message: ChatMessage):
        captured["message"] = message
        captured["inserted"] = True
        return message

    async def _fake_aupdate(_cls, message: ChatMessage):
        captured["message"] = message
        captured["updated"] = True
        return message

    async def _fake_get(_cls, chat_id, category_list=None, limit=10):
        return list(captured["existing"])

    monkeypatch.setattr(ChatMessageDao, "ainsert_one", classmethod(_fake_ainsert_one))
    monkeypatch.setattr(ChatMessageDao, "aupdate_message_model", classmethod(_fake_aupdate))
    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", classmethod(_fake_get))
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
    await linsight_execute_utils.persist_task_user_turn(chat_id="chat-5", user_id=1, question="帮我写周报", files=None)

    msg = capture_message["message"]
    assert msg.is_bot is False
    assert msg.chat_id == "chat-5"
    assert msg.category == "question"
    assert "帮我写周报" in msg.message


def _question_row(svid: str, chat_id: str, files: list[dict]) -> ChatMessage:
    return ChatMessage(
        id=11,
        is_bot=False,
        chat_id=chat_id,
        user_id=1,
        flow_id="",
        type="over",
        category="question",
        sender="User",
        message=json.dumps({"query": "总结下附件", "files": files}, ensure_ascii=False),
        files=json.dumps(files),
        extra=json.dumps({"linsight_session_version_id": svid}),
        tenant_id=1,
    )


def _ingested_session(svid: str, chat_id: str, files: list[dict]) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id=svid, session_id=chat_id, user_id=1, question="总结下附件", files=files, tenant_id=1
    )


async def test_question_row_carries_the_sv_pointer_so_the_worker_can_find_it(capture_message):
    """With the ingest deferred, everything the parse learns about the files
    arrives minutes after this row is written. The pointer is how the worker gets
    back to this exact row — the bot task turn has used the same one all along."""
    await linsight_execute_utils.persist_task_user_turn(
        chat_id="chat-6", user_id=1, question="总结下附件", files=[{"file_id": "v1"}], session_version_id="SV-6"
    )

    assert json.loads(capture_message["message"].extra)["linsight_session_version_id"] == "SV-6"


async def test_worker_back_fills_the_video_cover_onto_the_question_row(capture_message):
    """The poster frame is produced by the ingest, which now runs in the worker —
    so the chip that was persisted at submit has no cover to render and a
    task-mode video shows as a blank card on every reload. (The live session only
    looks right because the client stamps its own copy in memory.)"""
    row = _question_row("SV-6", "chat-6", [{"file_id": "v1", "filename": "clip.mp4"}])
    capture_message["existing"] = [row]
    session = _ingested_session(
        "SV-6",
        "chat-6",
        [{"file_id": "v1", "valid": True, "parsing_status": "completed", "cover_filepath": "chat/1/cover.jpg"}],
    )

    assert await linsight_execute_utils.annotate_task_user_turn_files(session) is True

    assert capture_message.get("updated") is True
    persisted = json.loads(capture_message["message"].message)["files"][0]
    assert persisted["cover_filepath"] == "chat/1/cover.jpg"
    assert persisted["parsing_status"] == "completed"
    # The mirrored column has to move with it — history rendering reads it too.
    assert json.loads(capture_message["message"].files)[0]["cover_filepath"] == "chat/1/cover.jpg"


async def test_back_fill_never_touches_another_turns_question_row(capture_message):
    """One conversation holds every turn's question. Matching on "the newest
    question row" would stamp turn N's parse result onto turn N+1's attachments;
    the SV pointer is what keeps them apart."""
    other = _question_row("SV-OTHER", "chat-6", [{"file_id": "v1", "filename": "clip.mp4"}])
    capture_message["existing"] = [other]
    session = _ingested_session("SV-6", "chat-6", [{"file_id": "v1", "cover_filepath": "chat/1/cover.jpg"}])

    assert await linsight_execute_utils.annotate_task_user_turn_files(session) is False
    assert capture_message.get("updated") is None


async def test_failed_task_turn_falls_back_to_error_message(capture_message):
    """A failed task (no answer) still writes a task turn, using the error message."""
    session = LinsightSessionVersion(
        id="SV-8",
        session_id="chat-8",
        user_id=1,
        question="q",
        output_result={"error_message": "执行失败"},
        tenant_id=1,
    )

    await linsight_execute_utils.persist_task_turn_message(session)

    msg = capture_message["message"]
    assert msg.category == "task"
    assert "执行失败" in msg.message
    assert json.loads(msg.extra)["linsight_session_version_id"] == "SV-8"


async def test_persist_upserts_existing_placeholder_row(capture_message):
    """If a task-turn row for this SV already exists (placeholder written at start),
    completion UPDATES it in place rather than inserting a duplicate."""
    placeholder = ChatMessage(
        id=42,
        is_bot=True,
        chat_id="chat-7",
        user_id=1,
        flow_id="",
        type="over",
        category="task",
        message="",
        extra=json.dumps({"linsight_session_version_id": "SV-9"}),
        tenant_id=1,
    )
    capture_message["existing"] = [placeholder]

    await linsight_execute_utils.persist_task_turn_message(_session(svid="SV-9", chat_id="chat-7"))

    assert capture_message.get("updated") is True
    assert capture_message.get("inserted") is None
    assert capture_message["message"].message == "最终答案"

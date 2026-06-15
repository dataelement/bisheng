"""F035 Track J (TJ-2) — unified submit session type.

Under the unified conversation model, a task turn lives inside a daily
workstation conversation (flow_type=WORKSTATION=15), never its own
flow_type=LINSIGHT=20 session. When ``submit_user_question`` is called without
a ``session_id`` (first turn, no daily session yet), it must create the session
as flow_type=15 — matching how ``workstation/chat_service`` mints daily chats —
so the conversation reads as one stream regardless of task mode (C8, design §3.1).

DAO / telemetry / file-processing are patched; the unit under test is the
session-creation branch of submit_user_question, not DB or MinIO access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.linsight.domain.services import workbench_impl
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl


@pytest.fixture
def patch_submit_io(monkeypatch: pytest.MonkeyPatch):
    """Isolate submit_user_question from DB/telemetry/MinIO; capture session + chat messages."""
    captured: dict = {"messages": []}

    async def _fake_insert_session(_cls, data: MessageSession):
        captured["session"] = data
        return data

    async def _fake_insert_version(_cls, data):
        return data

    async def _fake_insert_message(_cls, data: ChatMessage):
        captured["messages"].append(data)
        return data

    monkeypatch.setattr(MessageSessionDao, "async_insert_one", classmethod(_fake_insert_session))
    monkeypatch.setattr(LinsightSessionVersionDao, "insert_one", classmethod(_fake_insert_version))
    monkeypatch.setattr(ChatMessageDao, "ainsert_one", classmethod(_fake_insert_message))
    monkeypatch.setattr(LinsightWorkbenchImpl, "_process_submitted_files", AsyncMock(return_value=None))
    monkeypatch.setattr(workbench_impl.telemetry_service, "log_event", AsyncMock(return_value=None))

    return captured


async def test_submit_without_session_id_creates_workstation_session(patch_submit_io):
    """A fresh task turn (no session_id) creates a flow_type=15 session, not 20."""
    login_user = MagicMock()
    login_user.user_id = 1
    submit_obj = LinsightQuestionSubmitSchema(question="帮我写个周报", session_id=None)

    await LinsightWorkbenchImpl.submit_user_question(submit_obj, login_user)

    assert patch_submit_io["session"].flow_type == FlowType.WORKSTATION.value


async def test_submit_persists_user_question_turn(patch_submit_io):
    """submit writes the user question as a ChatMessage(category='question') in the stream."""
    login_user = MagicMock()
    login_user.user_id = 1
    submit_obj = LinsightQuestionSubmitSchema(question="帮我写个周报", session_id=None)

    await LinsightWorkbenchImpl.submit_user_question(submit_obj, login_user)

    user_turns = [m for m in patch_submit_io["messages"] if m.category == "question"]
    assert len(user_turns) == 1
    assert user_turns[0].is_bot is False
    assert "帮我写个周报" in user_turns[0].message

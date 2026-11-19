"""F035 Track J (TJ-1) — unified conversation read contract.

Under the unified conversation model, task-mode turns are persisted as plain
``ChatMessage`` rows in the same daily workstation conversation (flow_type=15),
marked with ``category='task'`` and carrying a pointer to the linsight execution
detail in ``extra.linsight_session_version_id`` (see C8 in 依赖与契约约定.md,
design §2.2 / §11).

These tests pin the READ side of that contract: ``WorkstationMessage.from_chat_message``
must surface, for the frontend renderer, (a) the message category so a task turn
can branch to the rich panel, and (b) the linsight session-version id so the
panel detail can be lazy-loaded. A normal turn must expose neither.

DAO layers (user / session lookup) are monkeypatched — the unit under test is the
pure ChatMessage -> WorkstationMessage field mapping, not DB access.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.user.domain.models.user import UserDao
from bisheng.workstation.domain.schemas.workstation_schema import WorkstationMessage


def _make_chat_message(
    *, id_: int, is_bot: bool, category: str, message: str, extra: dict | None = None, chat_id: str = "chat-1"
) -> ChatMessage:
    return ChatMessage(
        id=id_,
        is_bot=is_bot,
        chat_id=chat_id,
        user_id=1,
        flow_id="flow-1",
        type="assistant" if is_bot else "human",
        category=category,
        message=message,
        sender="",
        extra=json.dumps(extra) if extra else None,
        tenant_id=1,
        create_time=datetime(2026, 6, 15, 12, 0, 0),
        update_time=datetime(2026, 6, 15, 12, 0, 0),
    )


@pytest.fixture
def patch_daos(monkeypatch: pytest.MonkeyPatch):
    """Make UserDao.aget_user / MessageSessionDao.async_get_one resolve to stubs."""

    class _FakeUser:
        user_name = "tester"

    async def _fake_aget_user(_cls, _user_id):  # type: ignore[no-untyped-def]
        return _FakeUser()

    async def _fake_async_get_one(_cls, chat_id):  # type: ignore[no-untyped-def]
        return MessageSession(
            chat_id="chat-1",
            flow_id="flow-1",
            flow_name="",
            flow_type=FlowType.WORKSTATION.value,
            user_id=1,
            name="New Chat",
            tenant_id=1,
        )

    monkeypatch.setattr(UserDao, "aget_user", classmethod(_fake_aget_user))
    monkeypatch.setattr(MessageSessionDao, "async_get_one", classmethod(_fake_async_get_one))


async def test_task_turn_exposes_category_and_session_version_id(patch_daos):
    """A task-mode bot turn must surface category='task' and the SV pointer."""
    msg = _make_chat_message(
        id_=2,
        is_bot=True,
        category="task",
        message="最终答案",
        extra={"linsight_session_version_id": "SV-123"},
    )

    result = await WorkstationMessage.from_chat_message(msg)

    assert result.category == "task"
    assert result.linsightSessionVersionId == "SV-123"


async def test_normal_turn_has_no_session_version_id(patch_daos):
    """A normal answer turn must not be marked as task and carries no SV pointer."""
    msg = _make_chat_message(
        id_=1,
        is_bot=True,
        category="answer",
        message="普通回答",
    )

    result = await WorkstationMessage.from_chat_message(msg)

    assert result.category != "task"
    assert result.linsightSessionVersionId is None

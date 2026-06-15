"""F035 Track J (TJ-5, D2 symmetry) — daily chain sees task-turn answers.

In the unified model task turns are ``ChatMessage(category='task')`` rows in the
same conversation. For the "both directions feed the model" decision (D2), the
daily workstation chain's LLM history must include those task answers — so a
follow-up daily turn is aware of what the task produced.

``ChatMessageDao.aget_messages_by_chat_id`` is patched; the unit under test is
``WorkStationService.get_chat_history`` category whitelist + task→AIMessage map.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from langchain_core.messages import AIMessage

from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _task_turn(answer: str = "任务最终答案") -> ChatMessage:
    return ChatMessage(
        id=2,
        is_bot=True,
        chat_id="chat-1",
        user_id=1,
        flow_id="",
        type="over",
        category="task",
        message=answer,
        tenant_id=1,
        create_time=datetime(2026, 6, 15, 12, 0, 0),
        update_time=datetime(2026, 6, 15, 12, 0, 0),
    )


@pytest.fixture
def patch_messages(monkeypatch: pytest.MonkeyPatch):
    state: dict = {"categories": None, "rows": []}

    async def _fake(_cls, chat_id, categories=None, size=4):
        state["categories"] = categories
        return list(state["rows"])

    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", classmethod(_fake))
    return state


async def test_daily_history_includes_task_turn_as_ai_message(patch_messages):
    """A task-turn answer is surfaced to the daily chain as an AIMessage."""
    patch_messages["rows"] = [_task_turn("任务最终答案")]

    history = await WorkStationService.get_chat_history("chat-1", max_tokens=None)

    assert "task" in patch_messages["categories"]
    ai_msgs = [m for m in history if isinstance(m, AIMessage)]
    assert any("任务最终答案" in str(m.content) for m in ai_msgs)

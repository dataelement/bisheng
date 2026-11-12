"""F035 Track J (TJ-5, D2 symmetry) — daily chain sees task-turn answers.

In the unified model task turns are ``ChatMessage(category='task')`` rows in the
same conversation. For the "both directions feed the model" decision (D2), the
daily workstation chain's LLM history must include those task answers — so a
follow-up daily turn is aware of what the task produced.

``ChatMessageDao.aget_messages_by_chat_id`` is patched; the unit under test is
``WorkStationService.get_chat_history`` category whitelist + task→AIMessage map.
"""

from __future__ import annotations

import json
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
    state: dict = {"categories": None, "rows": [], "page_sizes": []}

    async def _fake(_cls, chat_id, categories=None, size=4, offset=0):
        state["categories"] = categories
        state["page_sizes"].append(size)
        end = len(state["rows"]) - offset
        return list(state["rows"][max(0, end - size) : end])

    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", classmethod(_fake))
    return state


async def test_daily_history_includes_task_turn_as_ai_message(patch_messages):
    """A task-turn answer is surfaced to the daily chain as an AIMessage."""
    patch_messages["rows"] = [_task_turn("任务最终答案")]

    history = await WorkStationService.get_chat_history("chat-1", max_tokens=None)

    assert "task" in patch_messages["categories"]
    ai_msgs = [m for m in history if isinstance(m, AIMessage)]
    assert any("任务最终答案" in str(m.content) for m in ai_msgs)


@pytest.mark.parametrize("partial", ["", "Partial answer"])
async def test_rate_limit_cards_do_not_consume_history_window(patch_messages, partial):
    question = _task_turn()
    question.category = "question"
    question.message = json.dumps({"query": "Original question"})
    failure = _task_turn()
    failure.category = "agent_answer"
    failure.message = json.dumps({"msg": partial, "events": []})
    failure.extra = json.dumps({"error": True, "error_type": "rate_limit"})
    patch_messages["rows"] = [*[_task_turn(f"Earlier {i}") for i in range(12)], question, *([failure] * 23)]

    history = await WorkStationService.get_chat_history("chat-1", size=10)

    assert [message.content for message in history] == [*[f"Earlier {i}" for i in range(3, 12)], "Original question"]
    assert all(size <= 10 for size in patch_messages["page_sizes"])


async def test_other_error_partial_answers_and_malformed_metadata_remain_in_history(patch_messages):
    rows = []
    for extra in ['{"error":true,"error_type":"network"}', "broken", "[]"]:
        row = _task_turn()
        row.category = "agent_answer"
        row.message = json.dumps({"msg": "Kept partial answer"})
        row.extra = extra
        rows.append(row)
    patch_messages["rows"] = rows
    history = await WorkStationService.get_chat_history("chat-1", size=3)
    assert [message.content for message in history] == ["Kept partial answer"] * 3


async def test_zero_history_size_does_not_query(patch_messages):
    assert await WorkStationService.get_chat_history("chat-1", size=0) == []
    assert patch_messages["page_sizes"] == []

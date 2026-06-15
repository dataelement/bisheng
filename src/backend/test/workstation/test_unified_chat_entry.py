"""F035 Track J (TJ-2 dispatch) — unified chat entry routes by task_mode.

Decision (user, 2026-06-15): one backend submit entry. The daily workstation
``/chat/completions`` gains a ``task_mode`` flag; ``stream_chat_completion``
dispatches — task_mode=False keeps the daily SSE agent flow, task_mode=True
hands off to the linsight task flow (create session + let the frontend connect
to the existing task-message-stream WS). Per-path streaming is reused; only the
ENTRY is unified.

Downstream handlers are patched; the unit under test is the routing decision.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.workstation.domain.services import chat_service


def _data(task_mode: bool) -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-06-15T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text="帮我写周报",
        task_mode=task_mode,
    )


@pytest.fixture
def patch_handlers(monkeypatch: pytest.MonkeyPatch):
    daily = AsyncMock(return_value="DAILY")
    task = AsyncMock(return_value="TASK")
    monkeypatch.setattr(chat_service, "_agent_stream_chat_completion", daily)
    monkeypatch.setattr(chat_service, "_task_mode_stream_completion", task)
    return {"daily": daily, "task": task}


async def test_task_mode_false_routes_to_daily(patch_handlers):
    result = await chat_service.stream_chat_completion(MagicMock(), _data(task_mode=False), MagicMock())

    assert result == "DAILY"
    patch_handlers["daily"].assert_awaited_once()
    patch_handlers["task"].assert_not_awaited()


async def test_task_mode_true_routes_to_task(patch_handlers):
    result = await chat_service.stream_chat_completion(MagicMock(), _data(task_mode=True), MagicMock())

    assert result == "TASK"
    patch_handlers["task"].assert_awaited_once()
    patch_handlers["daily"].assert_not_awaited()


def test_to_linsight_submit_maps_question_session_and_knowledge():
    """Sound field mapping: question + conversation + knowledge booleans.

    Tools/files are intentionally NOT mapped from daily-shaped fields — daily and
    task use different tool/file subsystems (flat ToolPayload vs grouped linsight
    tools; different upload buckets). Task-mode tools/files come from linsight-
    native selection (frontend TJ-6), not from these daily fields.
    """
    from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam

    data = APIChatCompletion(
        clientTimestamp="t",
        conversationId="chat-9",
        model="m",
        text="做个调研",
        task_mode=True,
        use_knowledge_base=UseKnowledgeBaseParam(
            personal_knowledge_enabled=True,
            organization_knowledge_ids=[1, 2],
        ),
    )

    submit = chat_service._to_linsight_submit(data)

    assert submit.question == "做个调研"
    assert submit.session_id == "chat-9"
    assert submit.personal_knowledge_enabled is True
    assert submit.org_knowledge_enabled is True  # derived from non-empty org ids


def test_to_linsight_submit_no_knowledge_defaults_false():
    data = APIChatCompletion(clientTimestamp="t", conversationId="c", model="m", text="hi", task_mode=True)

    submit = chat_service._to_linsight_submit(data)

    assert submit.org_knowledge_enabled is False
    assert submit.personal_knowledge_enabled is False

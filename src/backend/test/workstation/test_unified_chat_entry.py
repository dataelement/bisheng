"""The one chat entry: who serves a ``/chat/completions`` request.

``stream_chat_completion`` is called by two endpoints. The login-state endpoint
passes no ``session_subject``: the unified runtime (``run_send.unified_send``)
serves daily chat and deep research alike (F004). The Open API endpoint passes
its ``session_subject`` and keeps the daily agent flow; it never sends
``task_mode=True`` (an Open API task goes through ``OpenTaskModeService``).

Downstream handlers are patched; the unit under test is the routing decision,
plus ``_to_linsight_submit`` (F035 Track J), the mapping the task submit core uses.
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
    from bisheng.workstation.domain.services import run_send

    daily = AsyncMock(return_value="DAILY")
    unified = AsyncMock(return_value="UNIFIED")
    monkeypatch.setattr(chat_service, "_agent_stream_chat_completion", daily)
    monkeypatch.setattr(run_send, "unified_send", unified)
    return {"daily": daily, "unified": unified}


@pytest.mark.parametrize("task_mode", [False, True])
async def test_login_state_request_goes_to_the_unified_send_entry(patch_handlers, task_mode):
    register = AsyncMock()
    data = _data(task_mode=task_mode)
    data.skills = ["morning-report"]

    result = await chat_service.stream_chat_completion(MagicMock(), data, MagicMock(), memory_register=register)

    assert result == "UNIFIED"
    patch_handlers["daily"].assert_not_awaited()
    call = patch_handlers["unified"].await_args
    # The request reaches the send entry as sent (skill selection included) with the memory hook.
    assert call.args[1] is data and call.args[1].skills == ["morning-report"]
    assert call.kwargs == {"memory_register": register}


async def test_open_api_request_keeps_the_daily_agent_flow(patch_handlers):
    subject = MagicMock(name="session_subject")

    result = await chat_service.stream_chat_completion(
        MagicMock(), _data(task_mode=False), MagicMock(), session_subject=subject
    )

    assert result == "DAILY"
    patch_handlers["unified"].assert_not_awaited()
    assert patch_handlers["daily"].await_args.args[3] is subject


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


def test_to_linsight_submit_forwards_per_task_model():
    """The frontend-selected per-task model id must be forwarded, not dropped.

    Regression: _to_linsight_submit hard-coded model=None, so a task-mode turn
    always lost the selected model. _resolve_model then fell back to the tenant
    linsight_default_model_id and failed outright when that was unconfigured.
    """
    data = APIChatCompletion(clientTimestamp="t", conversationId="c", model="20", text="hi", task_mode=True)

    submit = chat_service._to_linsight_submit(data)

    assert submit.model == "20"


def test_to_linsight_submit_no_knowledge_defaults_false():
    data = APIChatCompletion(clientTimestamp="t", conversationId="c", model="m", text="hi", task_mode=True)

    submit = chat_service._to_linsight_submit(data)

    assert submit.org_knowledge_enabled is False
    assert submit.personal_knowledge_enabled is False


def test_to_linsight_submit_forwards_selected_skills():
    """The daily task-mode skill picker must reach the submit schema.

    Regression: _to_linsight_submit dropped skills entirely, so the stored SV had
    skills=None. That was masked while None meant "load all enabled skills"; once
    None means "no skills", an explicit pick that never arrived silently loaded
    nothing — the picker looked broken.
    """
    data = APIChatCompletion(
        clientTimestamp="t", conversationId="c", model="m", text="hi", task_mode=True, skills=["morning-report"]
    )

    submit = chat_service._to_linsight_submit(data)

    assert submit.skills == ["morning-report"]


def test_to_linsight_submit_no_skills_stays_none():
    data = APIChatCompletion(clientTimestamp="t", conversationId="c", model="m", text="hi", task_mode=True)

    submit = chat_service._to_linsight_submit(data)

    assert submit.skills is None


async def test_open_api_daily_turn_clears_stale_skill_selection(patch_handlers):
    data = _data(task_mode=False)
    data.skills = ["morning-report"]
    await chat_service.stream_chat_completion(MagicMock(), data, MagicMock(), session_subject=MagicMock())
    assert patch_handlers["daily"].await_args.args[1].skills == []
    assert data.skills == ["morning-report"]

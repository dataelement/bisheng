"""Task handoff must not own the lifetime of conversation naming."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.workstation.domain.schemas.chat import APIChatCompletion
from bisheng.workstation.domain.services import chat_service, task_submit_service


async def test_task_title_survives_handoff_disconnect(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    saved = []

    async def generate(_question, _llm, chat_id, _user, _request):
        started.set()
        await release.wait()
        saved.append(chat_id)

    monkeypatch.setattr(chat_service, "gen_title", generate)
    monkeypatch.setattr(chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", lambda *_a: None)
    monkeypatch.setattr(
        task_submit_service,
        "submit_task_turn",
        AsyncMock(return_value=(SimpleNamespace(name="New Chat"), SimpleNamespace(id="sv1", session_id="c1"))),
    )
    monkeypatch.setattr(chat_service.LLMService, "get_bisheng_llm", AsyncMock(return_value=object()))
    data = APIChatCompletion(clientTimestamp="t", model="m1", text="总结文档", task_mode=True)
    response = await chat_service._task_mode_stream_completion(MagicMock(), data, MagicMock())
    chunk = await anext(response.body_iterator)
    assert "linsight_task_handoff" in chunk
    await response.body_iterator.aclose()
    try:
        await asyncio.wait_for(started.wait(), 0.1)
        release.set()
        await asyncio.gather(*list(chat_service._BACKGROUND_TASKS))
        assert saved == ["c1"]
    finally:
        release.set()

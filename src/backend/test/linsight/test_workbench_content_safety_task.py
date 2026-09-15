"""F063 task-mode input intercept: no handoff, no session_version, leftover submit."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.linsight.api.endpoints import linsight as linsight_ep
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit
from bisheng.workstation.domain.services import chat_service

AUTO_REPLY = "当前对话内容违反相关规范，请修改后重新输入"
HIT = SensitiveWordCheckResult(
    enabled=True,
    hits=[SensitiveWordHit(word="禁", count=1)],
    auto_reply=AUTO_REPLY,
)


def _task_data(text: str = "帮我写周报") -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-07-29T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text=text,
        task_mode=True,
    )


def _patch_blocked_init(monkeypatch):
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")
    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(return_value=(ws_config, conversation, message, None, model_info, False)),
    )
    inserted: list = []

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    return inserted


async def _drain(response) -> list:
    return [chunk async for chunk in response.body_iterator]


async def test_task_mode_hit_skips_submit_and_handoff(monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: HIT),
    )
    inserted = _patch_blocked_init(monkeypatch)
    submit = AsyncMock()
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.submit_user_question",
        submit,
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(
        "bisheng.linsight.domain.utils.enqueue_session_for_execution",
        enqueue,
    )
    chunks = await _drain(await chat_service.stream_chat_completion(MagicMock(), _task_data("禁词"), MagicMock()))
    blob = "".join(c if isinstance(c, str) else str(c) for c in chunks)
    assert "linsight_task_handoff" not in blob
    assert AUTO_REPLY in blob
    submit.assert_not_awaited()
    enqueue.assert_not_awaited()
    rows = [row for row in inserted if row.category == "agent_answer"]
    assert len(rows) == 1
    assert json.loads(rows[0].message)["msg"] == AUTO_REPLY
    assert json.loads(rows[0].message)["events"] == [{"type": "text", "content": AUTO_REPLY}]


async def test_task_mode_miss_still_submits(monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    session_version = SimpleNamespace(id="sv-1", session_id="chat-1")
    submit = AsyncMock(return_value=(MagicMock(), session_version))
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.submit_user_question",
        submit,
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.utils.enqueue_session_for_execution",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.linsight.domain.utils.persist_task_turn_message",
        AsyncMock(),
    )
    monkeypatch.setattr(chat_service.LLMService, "get_bisheng_llm", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(chat_service, "gen_title", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "_TITLE_GEN_TIMEOUT_S", 0.1)
    await _drain(await chat_service._task_mode_stream_completion(MagicMock(), _task_data(), MagicMock()))
    submit.assert_awaited_once()


async def test_legacy_submit_hit_does_not_create_session(monkeypatch):
    monkeypatch.setattr(
        linsight_ep.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: HIT),
    )
    submit = AsyncMock()
    monkeypatch.setattr(linsight_ep.LinsightWorkbenchImpl, "submit_user_question", submit)
    login = MagicMock()
    login.user_id = 1
    login.tenant_id = 1
    resp = await linsight_ep.submit_linsight_workbench(
        LinsightQuestionSubmitSchema(question="禁词"),
        login,
    )
    chunks = await _drain(resp)
    blob = "".join(
        c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if isinstance(c, dict) else str(c)
        for c in chunks
    )
    assert "linsight_workbench_submit" not in blob
    assert "content_safety_blocked" in blob
    assert AUTO_REPLY in blob
    submit.assert_not_awaited()


async def test_legacy_submit_miss_still_submits(monkeypatch):
    monkeypatch.setattr(
        linsight_ep.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    session = MagicMock()
    session.model_dump.return_value = {"chat_id": "c1"}
    version = MagicMock()
    version.public_dump.return_value = {"id": "sv"}
    version.title = None
    submit = AsyncMock(return_value=(session, version))
    monkeypatch.setattr(linsight_ep.LinsightWorkbenchImpl, "submit_user_question", submit)
    monkeypatch.setattr(
        linsight_ep,
        "settings",
        SimpleNamespace(aget_all_config=AsyncMock(return_value={})),
    )
    monkeypatch.setattr(
        linsight_ep.LinsightWorkbenchImpl,
        "task_title_generate",
        AsyncMock(return_value={"task_title": "t"}),
    )
    monkeypatch.setattr(linsight_ep.LinsightSessionVersionDao, "insert_one", AsyncMock())
    login = MagicMock()
    login.user_id = 1
    login.tenant_id = 1
    resp = await linsight_ep.submit_linsight_workbench(
        LinsightQuestionSubmitSchema(question="写周报"),
        login,
    )
    await _drain(resp)
    submit.assert_awaited_once()

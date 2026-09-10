"""F063 daily-mode input intercept: skip LLM, persist auto-reply, ignore files."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.sensitive_word.domain.schemas import SensitiveWordCheckResult, SensitiveWordHit
from bisheng.workstation.domain.services import chat_service

AUTO_REPLY = "当前对话内容违反相关规范，请修改后重新输入"
HIT = SensitiveWordCheckResult(
    enabled=True,
    hits=[SensitiveWordHit(word="禁", count=1)],
    auto_reply=AUTO_REPLY,
)


class _Chunk:
    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


def _data(**kwargs) -> APIChatCompletion:
    payload = {
        "clientTimestamp": "2026-07-29T00:00:00Z",
        "conversationId": "chat-1",
        "model": "m1",
        "text": "创盈芯投资可行性分析",
    }
    payload.update(kwargs)
    return APIChatCompletion(**payload)


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch):
    inserted: list = []
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")
    state = {"chunks": ["前半段答案", "后半段答案"]}

    class _LLM:
        async def astream(self, _messages):
            for text in state["chunks"]:
                yield _Chunk(text)

    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(return_value=(ws_config, conversation, message, _LLM(), model_info, False)),
    )
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(
        chat_service.WorkStationService,
        "get_chat_history",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        chat_service.DepartmentFlowService,
        "resolve_limit_and_dept",
        AsyncMock(return_value=(0, None)),
    )
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations_sync", MagicMock(return_value=None))

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    return SimpleNamespace(inserted=inserted, init=chat_service._agent_initialize_chat)


async def _drain(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


def _answer_rows(inserted: list):
    return [row for row in inserted if row.category == "agent_answer"]


async def test_input_hit_skips_llm_and_emits_auto_reply(stream_env, monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: HIT),
    )
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    blob = "".join(chunks)
    assert "linsight_task_handoff" not in blob
    assert AUTO_REPLY in blob
    assert '"category": "agent_answer"' in blob
    assert '"type": "end"' in blob
    chat_service._prepare_tools.assert_not_awaited()
    assert stream_env.init.await_args.kwargs.get("skip_llm") is True
    rows = _answer_rows(stream_env.inserted)
    assert len(rows) == 1
    body = json.loads(rows[0].message)
    assert body["msg"] == AUTO_REPLY
    assert body["events"] == [{"type": "text", "content": AUTO_REPLY}]


async def test_files_only_does_not_block_on_filename(stream_env, monkeypatch):
    seen: list[str] = []

    def _evaluate(_tid, text):
        seen.append(text)
        return None

    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(_evaluate),
    )
    data = _data(text="", files=[{"filename": "禁词.pdf", "filepath": "/tmp/x"}])
    await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), data, MagicMock()))
    assert seen == [""]
    chat_service._prepare_tools.assert_awaited()


async def test_evaluate_none_enters_agent_loop(stream_env, monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    chat_service._prepare_tools.assert_awaited()
    assert any("前半段答案" in c for c in chunks)
    rows = _answer_rows(stream_env.inserted)
    assert json.loads(rows[0].message)["msg"] == "前半段答案后半段答案"

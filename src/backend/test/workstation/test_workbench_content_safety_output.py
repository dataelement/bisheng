"""F063 daily-mode output scan: 100-char full-buffer hit replaces the turn."""

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
    def __init__(self, content: str = "", reasoning: str = ""):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}


def _data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-07-29T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text="你好",
    )


class _HitOnLenScanner:
    def __init__(self, tenant_id, threshold=100, on_finish=False):
        self.fed: list[str] = []
        self._n = 0
        self.threshold = threshold
        self.on_finish = on_finish

    def feed(self, delta: str):
        self.fed.append(delta)
        self._n += len(delta)
        if not self.on_finish and self._n >= self.threshold:
            return HIT
        return None

    def finish(self):
        if self.on_finish:
            return HIT
        return None


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch):
    inserted: list = []
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")
    state = {"chunks": ["前半段答案", "后半段答案"], "reason": ""}

    class _LLM:
        async def astream(self, _messages):
            for text in state["chunks"]:
                yield _Chunk(text, reasoning=state["reason"])

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
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        staticmethod(lambda *_a, **_k: True),
    )

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    return SimpleNamespace(inserted=inserted, state=state)


async def _drain(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


def _answer_rows(inserted: list):
    return [row for row in inserted if row.category == "agent_answer"]


def _install_scanner(monkeypatch, scanner_cls):
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.stream_scanner.StreamContentSafetyScanner",
        scanner_cls,
    )


async def test_output_hit_at_100_replaces_persisted_answer(stream_env, monkeypatch):
    scanners: list[_HitOnLenScanner] = []

    class _Factory:
        def __new__(cls, tenant_id):
            inst = _HitOnLenScanner(tenant_id, threshold=100)
            scanners.append(inst)
            return inst

    _install_scanner(monkeypatch, _Factory)
    stream_env.state["chunks"] = ["x" * 60, "y" * 50, "should-not-appear"]
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    blob = "".join(chunks)
    assert AUTO_REPLY in blob
    rows = _answer_rows(stream_env.inserted)
    assert len(rows) == 1
    body = json.loads(rows[0].message)
    assert body["msg"] == AUTO_REPLY
    assert "should-not-appear" not in body["msg"]
    assert "x" * 60 not in body["msg"]
    assert scanners[0].fed == ["x" * 60, "y" * 50]


async def test_thinking_with_banned_word_is_not_scanned(stream_env, monkeypatch):
    scanners: list[_HitOnLenScanner] = []

    class _Factory:
        def __new__(cls, tenant_id):
            inst = _HitOnLenScanner(tenant_id, threshold=10_000)
            scanners.append(inst)
            return inst

    _install_scanner(monkeypatch, _Factory)
    stream_env.state["chunks"] = ["安全答案"]
    stream_env.state["reason"] = "禁" * 120
    await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    assert scanners
    assert scanners[0].fed == ["安全答案"]
    rows = _answer_rows(stream_env.inserted)
    assert json.loads(rows[0].message)["msg"] == "安全答案"


async def test_finish_remainder_under_100_replaces(stream_env, monkeypatch):
    class _Factory:
        def __new__(cls, tenant_id):
            return _HitOnLenScanner(tenant_id, threshold=100, on_finish=True)

    _install_scanner(monkeypatch, _Factory)
    stream_env.state["chunks"] = ["短答案"]
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    assert AUTO_REPLY in "".join(chunks)
    body = json.loads(_answer_rows(stream_env.inserted)[0].message)
    assert body["msg"] == AUTO_REPLY
    assert "短答案" not in body["msg"]


async def test_tools_astream_events_branch_also_scans(stream_env, monkeypatch):
    tool = MagicMock()
    tool.name = "search"
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([tool], [])))
    monkeypatch.setattr(chat_service, "_get_agent_max_iterations", AsyncMock(return_value=8))

    class _FakeAgent:
        async def astream_events(self, *_a, **_k):
            yield {
                "event": "on_chat_model_stream",
                "name": "model",
                "data": {"chunk": _Chunk("x" * 60)},
            }
            yield {
                "event": "on_chat_model_stream",
                "name": "model",
                "data": {"chunk": _Chunk("y" * 50)},
            }
            yield {
                "event": "on_chat_model_stream",
                "name": "model",
                "data": {"chunk": _Chunk("should-not-appear")},
            }

    monkeypatch.setattr("langgraph.prebuilt.ToolNode", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr("langgraph.prebuilt.create_react_agent", lambda *_a, **_k: _FakeAgent())

    class _Factory:
        def __new__(cls, tenant_id):
            return _HitOnLenScanner(tenant_id, threshold=100)

    _install_scanner(monkeypatch, _Factory)
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))
    body = json.loads(_answer_rows(stream_env.inserted)[0].message)
    assert body["msg"] == AUTO_REPLY
    assert "should-not-appear" not in "".join(chunks)
    assert "should-not-appear" not in body["msg"]

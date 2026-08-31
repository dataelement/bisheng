"""Daily-chat SSE stream: a torn-down stream must not lose the turn.

The answer row is written once, after the model stream finishes. `CancelledError`
and `GeneratorExit` are not `Exception` subclasses, so before the interrupt branch
existed a stream killed mid-flight (client navigated away, gateway read timeout,
worker restart) skipped the insert entirely — the conversation reloaded showing
only the question, even though the user had watched a full answer stream in.

These tests drive the no-tools branch (`bisheng_llm.astream`) because it is the
shortest path through the generator; the persistence code under test is shared
with the tool-calling branch.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.llm.domain.services.model_rate_limit import RateLimitObservation
from bisheng.llm.domain.services.model_rate_limit_state import ModelRateLimitState
from bisheng.workstation.domain.services import chat_service


class _Chunk:
    """Minimal stand-in for a LangChain streaming chunk."""

    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


def _data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-07-29T00:00:00Z",
        conversationId="chat-1",
        model="17",
        text="创盈芯投资可行性分析",
    )


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch):
    """Patch everything around the generator, leaving the stream body real.

    Returns a handle exposing the recorded DB writes plus a knob for what the
    model stream does after emitting its chunks.
    """
    inserted: list = []

    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")

    state = {"chunks": ["前半段答案", "后半段答案"], "after": None, "observation": None}

    class _LLM:
        async def astream(self, _messages):
            for text in state["chunks"]:
                yield _Chunk(text)
            if state["after"] is not None:
                raise state["after"]

    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(
            return_value=(
                ws_config,
                conversation,
                message,
                _LLM(),
                model_info,
                False,
                "execution-1",
                "attempt-1",
            )
        ),
    )

    class _RateLimitService:
        async def list_model_states(self, _tenant_id, model_ids):
            return {model_id: SimpleNamespace(status_version=0) for model_id in model_ids}

        async def observe_call_failure(self, _context, _exc):
            return state["observation"]

        async def observe_call_success(self, _context, _observed_status_version):
            return None

    monkeypatch.setattr(chat_service, "ModelRateLimitService", _RateLimitService)
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [])))
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

    return SimpleNamespace(inserted=inserted, state=state)


async def _drain(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


def _answer_rows(inserted: list):
    return [row for row in inserted if row.category == "agent_answer"]


async def test_cancelled_mid_stream_persists_partial_answer(stream_env):
    """A CancelledError after two deltas still saves what the model produced."""
    stream_env.state["after"] = asyncio.CancelledError()

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())

    with pytest.raises(asyncio.CancelledError):
        await _drain(response)

    rows = _answer_rows(stream_env.inserted)
    assert len(rows) == 1
    body = json.loads(rows[0].message)
    assert body["msg"] == "前半段答案后半段答案"
    assert [e["type"] for e in body["events"]] == ["text"]
    # The row is flagged as errored so history rendering can say it was cut short.
    assert json.loads(rows[0].extra)["error"] is True


async def test_consumer_abort_persists_partial_answer(stream_env):
    """The client hanging up (GeneratorExit via aclose) saves the turn too."""
    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())

    body_iterator = response.body_iterator
    async for _chunk in body_iterator:
        # Bail out as soon as the first answer delta lands, then close the
        # stream the way Starlette does when the client disconnects.
        if "agent_answer" in _chunk:
            break
    await body_iterator.aclose()

    rows = _answer_rows(stream_env.inserted)
    assert len(rows) == 1
    assert json.loads(rows[0].message)["msg"] == "前半段答案"
    assert json.loads(rows[0].extra)["error"] is True


async def test_completed_stream_persists_exactly_once(stream_env):
    """The happy path is untouched: one row, no error flag, async insert."""
    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))

    rows = _answer_rows(stream_env.inserted)
    assert len(rows) == 1
    assert json.loads(rows[0].message)["msg"] == "前半段答案后半段答案"
    assert json.loads(rows[0].extra) == {}
    chat_service.ChatMessageDao.insert_one.assert_not_called()
    # The terminal sentinel the frontend keys on for onEnd() still lands.
    assert any('"final": true' in c for c in chunks)


async def test_rate_limit_does_not_persist_a_bot_answer(stream_env):
    stream_env.state["after"] = RuntimeError("provider throttled")
    stream_env.state["observation"] = RateLimitObservation(
        execution_id="101",
        attempt_id="attempt-1",
        error_type="rate_limit",
        rate_limit_state=ModelRateLimitState.BUSY,
        busy_until=None,
        status_version=2,
        subject_id="101",
        model_id=17,
    )

    chunks = await _drain(await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock()))

    assert _answer_rows(stream_env.inserted) == []
    assert any("rate_limit" in chunk for chunk in chunks)


async def test_interrupt_after_completion_does_not_double_insert(stream_env):
    """A cancellation raised once the answer is already saved must not re-insert."""
    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())

    body_iterator = response.body_iterator
    async for _chunk in body_iterator:
        if '"final": true' in _chunk:
            break
    await body_iterator.aclose()

    assert len(_answer_rows(stream_env.inserted)) == 1

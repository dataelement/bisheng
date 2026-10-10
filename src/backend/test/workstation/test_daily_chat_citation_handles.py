"""F075 — the daily chat turn under the short-handle contract.

Drives the real SSE generator (no-tools branch) with a scripted model stream
and a handle table preloaded as if earlier turns had allocated it, then checks
what the reader receives, what is stored and which sources are bound.

AC-05 / AC-06: ``[Sn]`` never reaches the reader or the row; deltas, ``msg``
and ``events`` all carry the same converted text, even when a handle is split
across stream chunks.
AC-08 / AC-13: an unknown handle stays literal and is counted.
AC-10: a marker the model wrote itself is dropped and counted.
AC-11: history is built with the session's key → handle map.
AC-12: a source from an earlier turn is looked up and bound.
AC-14: an answer that cites nothing binds nothing.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER as E,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_SEPARATOR_MARKER as SEP,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_START_MARKER as S,
)
from bisheng.workstation.domain.services import chat_service, daily_citation

K1 = "knowledgesearch_aaaa1111:0"
K2 = "websearch_bbbb2222:1"
TABLE = {"S1": K1, "S2": K2}


class _Chunk:
    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


def _data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-09-30T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text="OKR 规则有什么变化",
    )


def _item(key: str) -> CitationRegistryItemSchema:
    citation_id, item_id = key.split(":")
    return CitationRegistryItemSchema(
        citationId=citation_id,
        itemId=item_id,
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=1,
            documentId=7,
            documentName="OKR规则.docx",
            items=[RagCitationItemSchema(itemId=item_id, content="chunk")],
        ),
    )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    inserted: list = []
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")
    state = {"chunks": [], "after": None}

    class _LLM:
        async def astream(self, _messages):
            for text in state["chunks"]:
                yield _Chunk(text)
            if state["after"] is not None:
                raise state["after"]

    async def _load(self):
        for handle, key in TABLE.items():
            self.register_handle(handle, key, {"key": key})

    history = AsyncMock(return_value=[])
    save_async = AsyncMock(return_value=None)
    save_sync = MagicMock(return_value=None)
    audit = MagicMock(wraps=daily_citation.log_citation_audit)
    cache_async = AsyncMock(side_effect=lambda ids: [_item(k) for k in (K1, K2) if k.split(":")[0] in ids])
    cache_sync = MagicMock(side_effect=lambda ids: [_item(k) for k in (K1, K2) if k.split(":")[0] in ids])

    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(return_value=(ws_config, conversation, message, _LLM(), model_info, False)),
    )
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(chat_service.DailyCitationScope, "load", _load)
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(chat_service.WorkStationService, "get_chat_history", history)
    monkeypatch.setattr(chat_service.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(0, None)))
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations", save_async)
    monkeypatch.setattr(chat_service, "save_message_citations_sync", save_sync)
    monkeypatch.setattr(chat_service, "log_citation_audit", audit)
    monkeypatch.setattr(daily_citation._runtime_cache, "get_citations_by_ids", cache_async)
    monkeypatch.setattr(daily_citation._runtime_cache, "get_citations_by_ids_sync", cache_sync)

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        staticmethod(lambda *_a, **_k: False),
    )
    return SimpleNamespace(
        inserted=inserted,
        state=state,
        history=history,
        save_async=save_async,
        save_sync=save_sync,
        audit=audit,
    )


async def _run(env) -> list[dict]:
    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())
    events = []
    async for chunk in response.body_iterator:
        for line in str(chunk).splitlines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def _streamed_text(events: list[dict]) -> str:
    return "".join(
        e["message"]["msg"] for e in events if e.get("category") == "agent_answer" and e.get("type") == "stream"
    )


def _answer_row(env):
    rows = [row for row in env.inserted if row.category == "agent_answer"]
    assert len(rows) == 1
    return json.loads(rows[0].message)


EXPECTED = f"结论。{S}{K1}{E}，另一句{S}{K1}{SEP}{K2}{E}，未知[S9]。"


async def test_handles_are_converted_before_the_reader_and_the_row_see_them(env):
    env.state["chunks"] = ["结论。[S", "1]，另一句[S1][", "S2]，未知[S9]。"]

    events = await _run(env)

    streamed = _streamed_text(events)
    assert streamed == EXPECTED
    assert "[S1]" not in streamed and "[S2]" not in streamed
    body = _answer_row(env)
    assert body["msg"] == EXPECTED
    assert [e["content"] for e in body["events"] if e["type"] == "text"] == [EXPECTED]
    end = [e for e in events if e.get("category") == "agent_answer" and e.get("type") == "end"][0]
    assert end["message"]["msg"] == EXPECTED


async def test_cited_sources_are_bound_including_earlier_turns(env):
    env.state["chunks"] = ["结论[S1][S2]。"]

    await _run(env)

    bound = env.save_async.await_args.kwargs["items"]
    assert sorted(i.citationId for i in bound) == ["knowledgesearch_aaaa1111", "websearch_bbbb2222"]


async def test_answer_citing_nothing_binds_nothing(env):
    env.state["chunks"] = ["一个没有引用的回答。"]

    await _run(env)

    assert env.save_async.await_args.kwargs["items"] == []


async def test_model_written_legacy_marker_is_dropped(env):
    env.state["chunks"] = [f"旧写法{S}knowledgesearch_ffff0000:0{E}。新写法[S1]。"]

    events = await _run(env)

    expected = f"旧写法。新写法{S}{K1}{E}。"
    assert _streamed_text(events) == expected
    assert _answer_row(env)["msg"] == expected
    stats = env.audit.call_args.kwargs["stats"]
    assert stats.legacy_markers == 1


async def test_audit_counts_unknown_handles(env):
    env.state["chunks"] = ["结论[S1]，编造[S9]。"]

    await _run(env)

    kwargs = env.audit.call_args.kwargs
    assert kwargs["stats"].unknown == ["S9"]
    assert len(kwargs["cited"]) == 1


async def test_history_is_built_with_the_session_handle_map(env):
    env.state["chunks"] = ["好的。"]

    await _run(env)

    assert env.history.await_args.kwargs["citation_key_to_handle"] == {K1: "S1", K2: "S2"}


async def test_interrupted_turn_stores_converted_text_and_binds_sync(env):
    env.state["chunks"] = ["结论。[S1]", "后文[S"]
    env.state["after"] = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _run(env)

    body = _answer_row(env)
    assert body["msg"] == f"结论。{S}{K1}{E}后文[S"
    bound = env.save_sync.call_args.kwargs["items"]
    assert [i.citationId for i in bound] == ["knowledgesearch_aaaa1111"]


async def test_tool_branch_converts_and_flushes_before_a_tool_call(env, monkeypatch):
    """Tool-calling branch: a handle split across chunks right before a tool
    call is released at the tool boundary, converted, and lands in its own
    text segment ahead of the tool event."""
    tool = MagicMock()
    tool.name = "search"
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([tool], [])))
    monkeypatch.setattr(chat_service, "_get_agent_max_iterations", AsyncMock(return_value=8))

    def _text(content):
        return {"event": "on_chat_model_stream", "name": "model", "data": {"chunk": _Chunk(content)}}

    class _FakeAgent:
        async def astream_events(self, *_a, **_k):
            yield _text("先查一下。[S")
            yield _text("1]")
            yield {"event": "on_tool_start", "name": "search", "run_id": "r1", "data": {"input": {"q": "x"}}}
            yield {"event": "on_tool_end", "name": "search", "run_id": "r1", "data": {"output": "[]"}}
            yield _text("结论[S2]。")

    monkeypatch.setattr("langgraph.prebuilt.ToolNode", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr("langgraph.prebuilt.create_react_agent", lambda *_a, **_k: _FakeAgent())

    events = await _run(env)

    expected = f"先查一下。{S}{K1}{E}结论{S}{K2}{E}。"
    assert _streamed_text(events) == expected
    body = _answer_row(env)
    assert body["msg"] == expected
    texts = [e["content"] for e in body["events"] if e["type"] == "text"]
    assert texts == [f"先查一下。{S}{K1}{E}", f"结论{S}{K2}{E}。"]


async def test_hang_up_on_the_final_flush_still_persists_the_turn(env):
    """An answer ending in a handle is held back until the end of the stream;
    the client hanging up on that last delta must still save the turn (the
    interruption branch only covers yields inside the try)."""
    env.state["chunks"] = ["结论[S1]"]

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), MagicMock())
    body_iterator = response.body_iterator
    answer_deltas = 0
    async for chunk in body_iterator:
        if '"agent_answer"' in chunk and '"stream"' in chunk:
            answer_deltas += 1
            if answer_deltas == 2:  # the flushed tail
                break
    await body_iterator.aclose()

    rows = [row for row in env.inserted if row.category == "agent_answer"]
    assert len(rows) == 1
    assert json.loads(rows[0].message)["msg"] == f"结论{S}{K1}{E}"

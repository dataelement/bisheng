"""Daily mode: memory stream signal, tool event redaction and end of turn (F132 T051).

Covers AC-09, AC-21, AC-37, AC-41, AC-87. The stream body of
``_agent_stream_chat_completion`` runs for real; the model is a scripted fake
agent that really calls the memory tools.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from bisheng.memory.domain.models.memory_session_cursor import STATE_PENDING
from bisheng.memory.domain.models.memory_turn_record import KIND_RETRIEVED, KIND_SUMMARY, KIND_WRITE
from test.workstation.memory_support import (  # noqa: F401  (fixtures)
    answer_rows,
    cursor,
    disable_my_memory,
    login_register,
    login_user,
    make_ctx,
    memory,
    memory_db,
    memory_runtime_config,
    register,
    run_turn,
    sse_events,
    stream_env,
    turn_rows,
)

SECRET = "用户每周三下午打羽毛球"
WRITE_STEP = ("tool", "memory_write", {"action": "remember", "content": SECRET, "type": "fact"})


def _flags(event):
    return event["message"]


async def test_ac21_write_emits_memory_signal_without_item_text(memory, stream_env):
    """AC-21: a successful memory_write puts a `memory` event on the stream with turn_id and flags, no item text."""
    stream_env.state.script = [WRITE_STEP, ("text", "记下了。")]
    chunks = await run_turn(stream_env)
    signals = sse_events(chunks, "memory")
    assert signals, "a memory event is expected after the write"
    for ev in signals:
        assert set(_flags(ev)) == {"turn_id", "has_write", "has_attribution"}
        assert SECRET not in json.dumps(ev, ensure_ascii=False)
    assert _flags(signals[0])["has_write"] is True
    writes = [r for r in turn_rows(memory.db) if r.kind == KIND_WRITE]
    assert len(writes) == 1 and writes[0].turn_id == _flags(signals[0])["turn_id"]
    # The last signal precedes the answer's end event and names the answer row.
    answer_id = answer_rows(stream_env.inserted)[0].id
    assert signals[-1]["message_id"] == answer_id
    order = [f"{b.get('category')}/{b.get('type')}" for b in sse_events(chunks)]
    assert order.index("memory/" + signals[-1]["type"]) < order.index("agent_answer/end")


async def test_ac87_resident_only_turn_signals_attribution_and_writes_summary(memory, stream_env):
    """AC-87: a turn that only injected resident memory still signals has_attribution and has its summary row."""
    await memory.service.write(make_ctx(), "remember", content="用户偏好简短回答", type="preference")
    chunks = await run_turn(stream_env)
    signals = sse_events(chunks, "memory")
    assert len(signals) == 1
    flags = _flags(signals[0])
    assert flags["has_attribution"] is True and flags["has_write"] is False
    summaries = [r for r in turn_rows(memory.db) if r.kind == KIND_SUMMARY]
    assert len(summaries) == 1
    row = summaries[0]
    assert row.turn_id == flags["turn_id"]
    assert row.resident_rev is not None and row.resident_day
    assert row.scene_class == "chat"
    assert row.message_id == answer_rows(stream_env.inserted)[0].id


async def test_ac87_search_only_turn_signals_attribution(memory, stream_env):
    """AC-87: a turn that only retrieved items (nothing resident) signals has_attribution."""
    # Experience items are never resident, so this turn's attribution comes from retrieval alone.
    await memory.service.write(make_ctx(), "remember", content="周报先写结论再写过程", type="experience")
    stream_env.state.script = [("tool", "memory_search", {"query": "周报怎么写"}), ("text", "按结论先行。")]
    chunks = await run_turn(stream_env)
    signals = sse_events(chunks, "memory")
    assert signals and _flags(signals[-1]) == {
        "turn_id": _flags(signals[-1])["turn_id"],
        "has_write": False,
        "has_attribution": True,
    }
    rows = turn_rows(memory.db)
    summary = next(r for r in rows if r.kind == KIND_SUMMARY)
    assert summary.resident_rev is None  # nothing was injected this turn
    retrieved = next(r for r in rows if r.kind == KIND_RETRIEVED)
    assert retrieved.message_id == answer_rows(stream_env.inserted)[0].id


async def test_no_signal_when_turn_used_no_memory(memory, stream_env):
    """AC-87: no resident block, no retrieval and no write: no memory event (nothing to attribute)."""
    chunks = await run_turn(stream_env)
    assert sse_events(chunks, "memory") == []
    summary = next(r for r in turn_rows(memory.db) if r.kind == KIND_SUMMARY)
    assert summary.resident_rev is None and summary.message_id == answer_rows(stream_env.inserted)[0].id


async def test_ac09_persisted_memory_tool_events_are_redacted(memory, stream_env):
    """AC-09: the answer row's events carry no memory item text, only {redacted, op, item_ids}."""
    await memory.service.write(make_ctx(), "remember", content="用户住在西湖区", type="fact")
    stream_env.state.script = [
        WRITE_STEP,
        ("tool", "memory_search", {"query": "西湖区 住"}),
        ("text", "好的。"),
    ]
    await run_turn(stream_env)
    row = answer_rows(stream_env.inserted)[0]
    assert SECRET not in row.message and "西湖区" not in row.message
    tool_events = [e for e in json.loads(row.message)["events"] if e.get("type") == "tool_call"]
    assert [e["tool_name"] for e in tool_events] == ["memory_write", "memory_search"]
    write, search = tool_events
    assert write["args"]["redacted"] is True and write["args"]["op"] == "remember"
    assert write["results"]["redacted"] is True and write["results"]["item_ids"]
    assert search["args"]["redacted"] is True
    assert search["results"]["redacted"] is True and search["results"]["op"] == "search"
    assert search["results"]["item_ids"]


async def test_ac09_streamed_memory_tool_events_are_redacted(memory, stream_env):
    """AC-09: agent_tool_call start/end events on the stream carry no memory item text."""
    stream_env.state.script = [WRITE_STEP, ("text", "好的。")]
    chunks = await run_turn(stream_env)
    tool_events = sse_events(chunks, "agent_tool_call")
    assert {ev["type"] for ev in tool_events} == {"start", "end"}
    for ev in tool_events:
        assert SECRET not in json.dumps(ev, ensure_ascii=False)
        assert ev["message"]["args"]["redacted"] is True
    end = next(ev for ev in tool_events if ev["type"] == "end")
    assert end["message"]["results"]["redacted"] is True


async def test_ac09_other_tools_are_not_redacted(memory, stream_env):
    """AC-09 scope: only memory_ tools are redacted; other tool events keep their content."""
    from langchain_core.tools import StructuredTool

    async def _web(q: str) -> str:
        return json.dumps([{"title": "天气", "snippet": "晴"}], ensure_ascii=False)

    stream_env.state.user_tools = [StructuredTool.from_function(coroutine=_web, name="web_search", description="d")]
    stream_env.state.script = [("tool", "web_search", {"q": "杭州天气"}), ("text", "晴。")]
    await run_turn(stream_env)
    event = json.loads(answer_rows(stream_env.inserted)[0].message)["events"][0]
    assert event["args"] == {"q": "杭州天气"} and event["results"][0]["snippet"] == "晴"


async def test_ac37_normal_end_binds_turn_and_marks_session_pending(memory, stream_env):
    """AC-37: on a normal end the turn records get the answer id and the session becomes pending."""
    stream_env.state.script = [WRITE_STEP, ("text", "记下了。")]
    await run_turn(stream_env)
    answer_id = answer_rows(stream_env.inserted)[0].id
    rows = turn_rows(memory.db)
    assert rows and all(r.message_id == answer_id for r in rows)
    row = cursor(memory.db)
    assert row.state == STATE_PENDING and row.last_message_id == answer_id


async def test_ac37_interrupted_turn_binds_and_marks_pending(memory, stream_env):
    """AC-37: the interrupt path (synchronous persistence) binds the turn and marks the session pending."""
    stream_env.state.script = [WRITE_STEP, ("text", "记下")]
    stream_env.state.after = asyncio.CancelledError()
    response = await stream_env.chat_service._agent_stream_chat_completion(
        MagicMock(),
        stream_env.data(),
        login_user(),
        memory_register=login_register(),
    )
    with pytest.raises(asyncio.CancelledError):
        _ = [c async for c in response.body_iterator]
    rows = answer_rows(stream_env.inserted)
    assert len(rows) == 1
    stream_env.chat_service.ChatMessageDao.insert_one.assert_called_once()  # the sync DAO ran
    assert SECRET not in rows[0].message
    answer_id = rows[0].id
    records = turn_rows(memory.db)
    assert records and all(r.message_id == answer_id for r in records)
    state = cursor(memory.db)
    assert state.state == STATE_PENDING and state.last_message_id == answer_id


async def test_ac41_disabled_turn_advances_watermark(memory, stream_env):
    """AC-41: a turn with memory off advances the watermark past itself, so it is never consolidated."""
    await register(memory.db)
    await disable_my_memory()
    chunks = await run_turn(stream_env)
    assert sse_events(chunks, "memory") == []
    answer_id = answer_rows(stream_env.inserted)[0].id
    row = cursor(memory.db)
    assert row.watermark_message_id == answer_id and row.state != STATE_PENDING
    assert turn_rows(memory.db) == []


async def test_ac10_unregistered_path_never_touches_the_session_row(memory, stream_env):
    """AC-10: the open-API path (no register) writes no turn records and leaves the session row alone."""
    await register(memory.db)
    before = cursor(memory.db).model_dump()
    stream_env.state.script = [("text", "好的。")]
    await run_turn(stream_env, registered=False)
    assert cursor(memory.db).model_dump() == before
    assert turn_rows(memory.db) == []

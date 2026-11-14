"""F132 T055: assistant memory tool redaction and the ``memory`` signal (Wave 9).

Covers AC-09, AC-21, AC-87. The real ``AsyncGptsDebugCallbackHandler`` is driven
by the real LangChain callback manager; only the message DAO and the websocket
are replaced.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from bisheng.api.v1 import callback as callback_module
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler
from bisheng.memory.domain.services.memory_service import MemoryService
from bisheng.memory.domain.services.redaction import replay_placeholder
from bisheng.memory.domain.services.tools import build_memory_tools
from bisheng.memory.domain.services.turn_record import TurnRecordService
from bisheng_langchain.gpts.message_types import LiberalToolMessage
from test.assistant.memory_support import (
    EXECUTORS,
    build_agent,
    client_slice,
    final_reply,
    register,
    seed_assistant,
    seed_chat,
    tool_reply,
    wired,  # noqa: F401  (pytest fixture)
)
from test.memory.conftest import (  # noqa: F401  (pytest fixtures)
    TENANT_A,
    audit_rows,
    details,
    index,
    kv,
    make_ctx,
    memory_db,
    memory_runtime_config,
    service,
    tenant_ctx,
)

SECRET = "用户的护照将在 2027-03-01 到期"
WRITE_ARGS = {"action": "remember", "content": SECRET, "type": "fact"}


class FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, data: dict):
        self.frames.append(data)


@pytest.fixture
def rows(monkeypatch):
    persisted = []

    def insert_one(row):
        persisted.append(row)
        return row

    monkeypatch.setattr(callback_module.ChatMessageDao, "insert_one", staticmethod(insert_one))
    return persisted


@pytest.fixture
async def enabled_chat(wired, tenant_ctx):  # noqa: F811
    tenant_ctx(TENANT_A)
    seed_assistant(wired.db, enabled=True)
    seed_chat(wired.db)
    await register()
    return wired


def _handler(ws, chat_id="chat-a1"):
    # Same kwargs as ChatClient.init_gpts_callback.
    return AsyncGptsDebugCallbackHandler(
        websocket=ws, flow_id="asst-mem-1", chat_id=chat_id, user_id=101, stream_queue=None
    )


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _memory_frames(ws):
    return [f for f in ws.frames if f.get("category") == "memory"]


def _tool_frames(ws):
    return [f for f in ws.frames if f.get("category") in ("tool", "flow", "knowledge")]


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac09_memory_tool_redacted_in_result_rows_callback_rows_and_ws(executor, enabled_chat, rows):
    """AC-09: run()-derived tool_call/tool_result rows, callback rows (message and
    intermediate_steps) and WebSocket tool frames carry no memory text."""
    ws = FakeWebSocket()
    agent, _ = await build_agent(executor, [tool_reply(executor, "memory_write", WRITE_ARGS), final_reply(executor)])
    history: list = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]

    result = await agent.run("记一下护照到期日", history, [_handler(ws)])

    _, kinds = client_slice(result, history)
    for one in result[len(history) : -1]:
        if isinstance(one, (AIMessage, ToolMessage)):
            dumped = one.model_dump_json()
            assert SECRET not in dumped and "redacted" in dumped
    if executor == "function call":
        assert kinds == ["tool_call", "tool_result"]
    (row,) = rows
    assert row.category == "tool"
    assert SECRET not in row.message and SECRET not in (row.intermediate_steps or "")
    stored = json.loads(row.message)
    assert stored["input_str"] and json.loads(stored["input_str"])["redacted"] is True
    assert json.loads(stored["output"])["redacted"] is True
    assert stored["serialized"] == {"name": "memory_write"}
    frames = _tool_frames(ws)
    assert [f["type"] for f in frames] == ["start", "end"]
    assert SECRET not in _dump(frames)


async def test_ac09_error_path_redacted_by_run_id(enabled_chat, rows, make_ctx, monkeypatch):
    """AC-09: on_tool_error has no tool name; the run_id alone identifies the memory call."""

    async def _boom(self, *a, **k):
        raise RuntimeError(f"db down while saving {SECRET}")

    monkeypatch.setattr(MemoryService, "write", _boom)
    ws = FakeWebSocket()
    (write_tool, _) = build_memory_tools(make_ctx(chat_id="chat-a1"))

    with pytest.raises(RuntimeError):
        await write_tool.ainvoke(WRITE_ARGS, config={"callbacks": [_handler(ws)]})

    (row,) = rows
    assert SECRET not in row.message and SECRET not in row.intermediate_steps
    assert SECRET not in _dump(ws.frames)
    assert json.loads(row.message)["serialized"] == {"name": "memory_write"}


async def test_ac09_debug_run_redacts_ws_without_persisting(enabled_chat, rows, make_ctx):
    """AC-09: debug runs (no chat_id) only stream, and the stream is redacted too."""
    ws = FakeWebSocket()
    (write_tool, _) = build_memory_tools(make_ctx(chat_id="chat-a1"))
    await write_tool.ainvoke(WRITE_ARGS, config={"callbacks": [_handler(ws, chat_id="")]})
    assert rows == []
    assert len(_tool_frames(ws)) == 2 and SECRET not in _dump(ws.frames)


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac09_non_memory_tool_untouched(executor, enabled_chat, rows):
    """AC-09 (negative): other tools keep their input and output in all three sinks."""

    async def _lookup(city: str) -> str:
        return f"{city} 晴 25 度"

    lookup = StructuredTool.from_function(coroutine=_lookup, name="weather", description="weather")
    ws = FakeWebSocket()
    agent, _ = await build_agent(
        executor, [tool_reply(executor, "weather", {"city": "杭州"}), final_reply(executor)], tools=[lookup]
    )
    history: list = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]
    result = await agent.run("杭州天气", history, [_handler(ws)])

    (row,) = rows
    assert "杭州" in row.message and "晴 25 度" in row.message and "晴 25 度" in row.intermediate_steps
    assert "晴 25 度" in _dump(_tool_frames(ws))
    if executor == "function call":
        assert client_slice(result, history)[1] == ["tool_call", "tool_result"]
        assert "晴 25 度" in result[len(history) : -1][1].content


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac09_replayed_memory_result_rendered_neutral(executor, enabled_chat, rows):
    """AC-09 (decision 10): next turn replays the redacted result as a neutral sentence."""
    first, _ = await build_agent(
        executor, [tool_reply(executor, "memory_write", WRITE_ARGS, "call_w"), final_reply(executor, "记住了")]
    )
    history: list = [HumanMessage(content="earlier q"), AIMessage(content="earlier a")]
    result = await first.run("记一下护照到期日", history)
    # Rebuild the history exactly as ChatClient.get_latest_history does from stored rows.
    replay = [HumanMessage(content="记一下护照到期日")]
    for one in result[len(history) : -1]:
        if isinstance(one, AIMessage):
            replay.append(AIMessage(**json.loads(one.model_dump_json())))
        elif isinstance(one, ToolMessage):
            replay.append(LiberalToolMessage(**json.loads(one.model_dump_json())))
    replay.append(AIMessage(content="记住了"))
    if executor == "ReAct":
        # ReAct never persists tool rows (V5); feed one stored row by hand to check replay.
        replay.insert(1, AIMessage(content="", tool_calls=[{"name": "memory_write", "args": {}, "id": "c1"}]))
        replay.insert(
            2, LiberalToolMessage(content='{"redacted": true, "op": "remember", "item_ids": []}', tool_call_id="c1")
        )

    second, llm = await build_agent(executor, [final_reply(executor)])
    await second.run("护照什么时候到期", replay)

    sent = llm.received[-1]
    replayed = [x for x in sent if isinstance(x, ToolMessage)]
    if executor == "function call":
        assert replayed and all(x.content == replay_placeholder() for x in replayed)
    else:
        assert replay_placeholder() in _dump([str(x.content) for x in sent])
    assert '"redacted"' not in _dump([str(x.content) for x in sent])


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac21_write_sends_memory_signal_without_text(executor, enabled_chat, rows):
    """AC-21: a successful explicit write sends a ``memory`` WebSocket message with the turn id
    and flags, never the item text."""
    ws = FakeWebSocket()
    agent, _ = await build_agent(executor, [tool_reply(executor, "memory_write", WRITE_ARGS), final_reply(executor)])

    await agent.run("记一下护照到期日", [], [_handler(ws)])

    signals = _memory_frames(ws)
    assert signals, "no memory signal sent"
    payload = signals[-1]["message"]
    assert set(payload) == {"turn_id", "has_write", "has_attribution"}
    assert payload["turn_id"] == agent.memory_turn.ctx.turn_id
    assert payload["has_write"] is True
    assert SECRET not in _dump(signals)


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac87_resident_only_turn_has_no_attribution_but_writes_summary(
    executor, enabled_chat, rows, make_ctx, service
):
    """AC-87: resident memory rides along every turn, so a turn that only injected it sends no
    signal; it still has a summary row (with resident rev and day)."""
    await service.write(make_ctx(), "remember", content="用户常驻上海", type="fact")
    ws = FakeWebSocket()
    agent, _ = await build_agent(executor, [final_reply(executor)])

    await agent.run("你好", [], [_handler(ws)])

    assert _memory_frames(ws) == []
    ctx = agent.memory_turn.ctx
    record = await TurnRecordService.get_for_owner(ctx, turn_id=ctx.turn_id)
    assert record["summary"]["resident_rev"] is not None and record["summary"]["resident_day"]
    assert record["summary"]["scene_class"] == "chat"


@pytest.mark.parametrize("executor", EXECUTORS)
async def test_ac87_retrieval_only_turn_signals_attribution(executor, enabled_chat, rows, make_ctx, service):  # noqa: F811
    """AC-87: a turn that only retrieved items (experience items are never resident) signals
    attribution; a turn with no resident block and no retrieval sends no signal but still
    writes its summary row."""
    await service.write(make_ctx(), "remember", content="订会员卡优惠时先查金卡权益", type="experience")
    quiet_ws = FakeWebSocket()
    quiet, _ = await build_agent(executor, [final_reply(executor)])
    await quiet.run("你好", [], [_handler(quiet_ws)])
    assert quiet.memory_turn.resident_text == ""
    assert _memory_frames(quiet_ws) == []
    ctx = quiet.memory_turn.ctx
    assert (await TurnRecordService.get_for_owner(ctx, turn_id=ctx.turn_id))["summary"] is not None

    ws = FakeWebSocket()
    agent, _ = await build_agent(
        executor, [tool_reply(executor, "memory_search", {"query": "会员卡 金卡"}), final_reply(executor)]
    )
    await agent.run("会员卡有什么经验", [], [_handler(ws)])
    (signal,) = _memory_frames(ws)
    assert signal["message"]["has_attribution"] is True and signal["message"]["has_write"] is False
    ctx = agent.memory_turn.ctx
    assert (await TurnRecordService.get_for_owner(ctx, turn_id=ctx.turn_id))["retrieved_item_ids"]


def test_ac09_anthropic_tool_use_content_blocks_are_redacted():
    """AC-09: Anthropic also puts tool calls in content as tool_use blocks with raw input."""
    from langchain_core.messages import AIMessage

    from bisheng.api.services import assistant_memory

    secret = {"action": "remember", "content": "用户的私人行程", "type": "fact"}
    message = AIMessage(
        content=[
            {"type": "text", "text": "好的"},
            {"type": "tool_use", "id": "tu_1", "name": "memory_write", "input": secret},
            {"type": "tool_use", "id": "tu_2", "name": "web_search", "input": {"q": "天气"}},
        ],
        tool_calls=[
            {"id": "tu_1", "name": "memory_write", "args": secret},
            {"id": "tu_2", "name": "web_search", "args": {"q": "天气"}},
        ],
    )
    out = assistant_memory.finalize_result([message])[0]
    assert "用户的私人行程" not in out.model_dump_json()
    assert out.content[2]["input"] == {"q": "天气"}

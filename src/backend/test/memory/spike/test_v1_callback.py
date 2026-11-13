"""F132 Wave 0 spike V1 (T002): assistant tool callbacks and memory-tool redaction.

Experimental code. Delete after Wave 9.

What this spike establishes against the real ``AsyncGptsDebugCallbackHandler``
(``bisheng/api/v1/callback.py``) driven by the real LangChain callback manager
(``StructuredTool.ainvoke`` with ``config={"callbacks": [...]}``):

1. ``on_tool_start`` receives the tool name in ``serialized["name"]`` and a
   ``run_id`` UUID; the handler caches the start payload under ``run_id.hex``.
2. ``on_tool_end`` receives the same ``run_id`` plus ``name=<tool name>``
   (langchain_core ``BaseTool.arun`` passes ``name=self.name``).
3. ``on_tool_error`` receives the same ``run_id`` but NO ``name`` kwarg
   (langchain_core calls ``on_tool_error(error, tool_call_id=...)``), so the
   persisted row falls back to category ``tool``. Redaction on the error path
   must therefore key on ``run_id``, not on ``kwargs["name"]``.
4. Unredacted, the raw tool input and output reach three sinks: the websocket
   start frame, the websocket end frame, and the ``ChatMessage`` row
   (``message`` and ``intermediate_steps``).
5. A redaction keyed on ``run_id`` (flag set in on_tool_start, consulted in
   on_tool_end / on_tool_error) removes the raw content from all sinks.
"""

import json
import uuid
from typing import Any

import pytest
from langchain_core.tools import StructuredTool, ToolException

from bisheng.api.v1 import callback as callback_module
from bisheng.api.v1.callback import AsyncGptsDebugCallbackHandler

SECRET_INPUT = "my passport number is SECRET-IN-42"
SECRET_OUTPUT = "user lives at SECRET-OUT-99"


class _FakeWebSocket:
    def __init__(self):
        self.frames: list[dict] = []

    async def send_json(self, data: dict):
        self.frames.append(data)


@pytest.fixture
def sinks(monkeypatch):
    rows: list[Any] = []

    def insert_one(row):
        rows.append(row)
        return row

    # The handler persists through ChatMessageDao.insert_one (sync DAO called
    # from the async callback: callback.py:532 and :574).
    monkeypatch.setattr(callback_module.ChatMessageDao, "insert_one", staticmethod(insert_one))
    return rows


def _handler(ws, handler_cls=AsyncGptsDebugCallbackHandler, chat_id="chat-1"):
    # Same kwargs as ChatClient.init_gpts_callback (common/chat/client.py:312-320).
    return handler_cls(websocket=ws, flow_id="assistant-1", chat_id=chat_id, user_id=7, stream_queue=None)


def _probe_tool(name="memory_probe"):
    async def _arun(query: str) -> str:
        return SECRET_OUTPUT

    return StructuredTool.from_function(coroutine=_arun, name=name, description="probe")


def _failing_tool(name="memory_probe"):
    async def _arun(query: str) -> str:
        raise ValueError("boom SECRET-OUT-99")

    return StructuredTool.from_function(coroutine=_arun, name=name, description="probe", handle_tool_error=False)


class _Spy(AsyncGptsDebugCallbackHandler):
    """Records the raw kwargs LangChain hands to the handler."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[tuple[str, dict]] = []

    async def on_tool_start(self, serialized, input_str, **kwargs):
        self.calls.append(("start", {"serialized": serialized, "input_str": input_str, **kwargs}))
        await super().on_tool_start(serialized, input_str, **kwargs)
        # Cache is keyed by run_id.hex right after start (callback.py:480).
        self.calls.append(("cache_after_start", dict(self.tool_cache)))

    async def on_tool_end(self, output, **kwargs):
        self.calls.append(("end", {"output": output, **kwargs}))
        await super().on_tool_end(output, **kwargs)

    async def on_tool_error(self, error, **kwargs):
        self.calls.append(("error", {"error": error, **kwargs}))
        await super().on_tool_error(error, **kwargs)


async def test_unredacted_start_end_leaks_to_ws_and_db_and_run_id_correlates(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, _Spy)

    await _probe_tool().ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})

    start = next(c for k, c in handler.calls if k == "start")
    end = next(c for k, c in handler.calls if k == "end")
    cache_after_start = next(c for k, c in handler.calls if k == "cache_after_start")

    # (1) on_tool_start gets the tool name.
    assert start["serialized"]["name"] == "memory_probe"
    # (2) on_tool_end gets the name as a kwarg and the SAME run_id.
    assert end["name"] == "memory_probe"
    assert isinstance(start["run_id"], uuid.UUID)
    assert start["run_id"] == end["run_id"]
    assert list(cache_after_start) == [start["run_id"].hex]
    assert handler.tool_cache == {}  # popped at callback.py:545

    # (4) Raw content reaches both websocket frames ...
    start_frame, end_frame = ws.frames
    assert start_frame["type"] == "start" and end_frame["type"] == "end"
    assert SECRET_INPUT in start_frame["message"] and SECRET_INPUT in start_frame["intermediate_steps"]
    assert SECRET_OUTPUT in end_frame["message"] and SECRET_OUTPUT in end_frame["intermediate_steps"]
    # ... and the persisted ChatMessage row (category=tool: no flow_/knowledge_ prefix).
    (row,) = sinks
    assert row.category == "tool"
    assert SECRET_INPUT in row.message and SECRET_OUTPUT in row.message
    assert SECRET_INPUT in row.intermediate_steps and SECRET_OUTPUT in row.intermediate_steps
    # All three sinks carry the same run_id in extra.
    run_hex = start["run_id"].hex
    assert json.loads(start_frame["extra"])["run_id"] == run_hex
    assert json.loads(end_frame["extra"])["run_id"] == run_hex
    assert json.loads(row.extra)["run_id"] == run_hex


async def test_error_path_has_run_id_but_no_name(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, _Spy)

    with pytest.raises(ValueError):
        await _failing_tool().ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})

    start = next(c for k, c in handler.calls if k == "start")
    err = next(c for k, c in handler.calls if k == "error")
    # (3) same run_id, but no tool name on the error path.
    assert err["run_id"] == start["run_id"]
    assert "name" not in err
    (row,) = sinks
    # Persisted category is derived from kwargs.get("name") -> None -> "tool"
    # (callback.py:572); the ws frame uses the cached start category (:558).
    assert row.category == "tool"
    assert SECRET_INPUT in row.message and "SECRET-OUT-99" in row.message
    end_frame = ws.frames[-1]
    assert "SECRET-OUT-99" in end_frame["intermediate_steps"]


async def test_debug_run_without_chat_id_sends_but_does_not_persist(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, chat_id="")
    await _probe_tool().ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})
    assert sinks == []  # callback.py:526-529
    assert len(ws.frames) == 2  # still sent over the websocket


# ---------------------------------------------------------------------------
# (5) Prototype of the planned redaction, keyed on run_id. The production
# version goes inside AsyncGptsDebugCallbackHandler itself (see v-assistant.md);
# this subclass only proves the hook points carry enough information.
# ---------------------------------------------------------------------------

REDACTED = json.dumps({"redacted": True, "op": "probe", "item_ids": []})


class _RedactingHandler(AsyncGptsDebugCallbackHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._memory_runs: set[str] = set()

    async def on_tool_start(self, serialized, input_str, **kwargs):
        if serialized.get("name", "").startswith("memory_"):
            self._memory_runs.add(kwargs["run_id"].hex)
            input_str = REDACTED
            serialized = {"name": serialized["name"]}
            kwargs.pop("inputs", None)
        await super().on_tool_start(serialized, input_str, **kwargs)

    async def on_tool_end(self, output, **kwargs):
        if kwargs["run_id"].hex in self._memory_runs:
            self._memory_runs.discard(kwargs["run_id"].hex)
            output = REDACTED
        await super().on_tool_end(output, **kwargs)

    async def on_tool_error(self, error, **kwargs):
        # No name here: only the run_id says this was a memory tool.
        if kwargs["run_id"].hex in self._memory_runs:
            self._memory_runs.discard(kwargs["run_id"].hex)
            error = ToolException("memory operation failed")
        await super().on_tool_error(error, **kwargs)


def _dump(ws_frames, rows) -> str:
    return json.dumps(ws_frames, ensure_ascii=False, default=str) + "".join(
        f"{r.message}{r.intermediate_steps}" for r in rows
    )


async def test_run_id_keyed_redaction_removes_content_from_all_sinks(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, _RedactingHandler)
    await _probe_tool().ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})
    dumped = _dump(ws.frames, sinks)
    assert "SECRET-IN-42" not in dumped and "SECRET-OUT-99" not in dumped
    assert '\\"redacted\\": true' in dumped or '"redacted": true' in dumped
    (row,) = sinks
    assert json.loads(row.message)["tool_key"] == "memory_probe"


async def test_run_id_keyed_redaction_on_error_path(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, _RedactingHandler)
    with pytest.raises(ValueError):
        await _failing_tool().ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})
    dumped = _dump(ws.frames, sinks)
    assert "SECRET-IN-42" not in dumped and "SECRET-OUT-99" not in dumped


async def test_non_memory_tool_is_untouched(sinks):
    ws = _FakeWebSocket()
    handler = _handler(ws, _RedactingHandler)
    await _probe_tool(name="web_probe").ainvoke({"query": SECRET_INPUT}, config={"callbacks": [handler]})
    dumped = _dump(ws.frames, sinks)
    assert "SECRET-IN-42" in dumped and "SECRET-OUT-99" in dumped

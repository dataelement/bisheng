"""F069 T022: per-turn source table + one-shot "add [Sn]" reminder (AC-08, AC-15).

Pure-function style with a ``_FakeReq`` stand-in for langchain's ``ModelRequest``
and an in-memory Redis fake patched over ``get_redis_client`` in the middleware
module; no real Redis, no real agent graph.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger

from bisheng.citation.domain.services.citation_handle_service import HANDLE_TTL_SECONDS, handle_redis_key
from bisheng.citation.domain.services.linsight_citation_scope import LinsightCitationScope
from bisheng.linsight.domain.services import citation_source_middleware as mod
from bisheng.linsight.domain.services.citation_source_middleware import (
    NUDGE_LOG_PREFIX,
    SOURCE_TABLE_HEADER,
    SOURCE_TABLE_OVERFLOW_LINE,
    LinsightCitationSourceMiddleware,
)

SVID = "svid-1"
SESSION_ID = "session-1"


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------
class _FakeReq:
    """Minimal ModelRequest: ``messages`` + ``state`` + immutable ``override``."""

    def __init__(self, messages: list, state: dict | None = None, **extra):
        self.messages = list(messages)
        self.state = state
        for key, value in extra.items():
            setattr(self, key, value)

    def override(self, **kw):
        merged = {"messages": self.messages, "state": self.state}
        merged.update(kw)
        return _FakeReq(**merged)


class _FakeRedis:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.set_calls: list[dict] = []

    async def ahget(self, name, key):
        return self.store.get((name, key))

    async def ahset(self, name, key=None, value=None, mapping=None, items=None, expiration=3600):
        self.store[(name, key)] = value
        self.set_calls.append({"name": name, "key": key, "value": value, "expiration": expiration})
        return 1


class _BrokenRedis:
    async def ahget(self, name, key):
        raise ConnectionError("redis down")

    async def ahset(self, *args, **kwargs):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch) -> _FakeRedis:
    redis = _FakeRedis()
    monkeypatch.setattr(mod, "get_redis_client", AsyncMock(return_value=redis))
    return redis


@pytest.fixture
def nudge_log():
    """loguru records as (level, message); caplog does not see loguru."""
    records: list[tuple[str, str]] = []
    sink_id = logger.add(lambda msg: records.append((msg.record["level"].name, msg.record["message"])), level="INFO")
    try:
        yield records
    finally:
        logger.remove(sink_id)


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------
def _scope(n: int = 3, enabled: bool = True) -> LinsightCitationScope:
    scope = LinsightCitationScope(svid=SVID, session_id=SESSION_ID, enabled=enabled)
    for i in range(1, n + 1):
        if i % 2:
            entry = {"type": "rag", "title": f"知识文档{i}", "loc": f"第{i}页"}
        else:
            entry = {"type": "web", "title": f"网页标题{i}", "loc": ""}
        scope.register_handle(f"S{i}", f"key-{i}", entry)
    return scope


def _write_turn(
    file_path: str,
    content: str,
    *,
    tool: str = "write_file",
    call_id: str = "call-1",
    status: str = "success",
    result: str = "Updated file output/x.md",
) -> list:
    arg_name = "new_string" if tool == "edit_file" else "content"
    args = {"file_path": file_path, arg_name: content}
    if tool == "edit_file":
        args["old_string"] = "old"
    return [
        HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[{"name": tool, "args": args, "id": call_id, "type": "tool_call"}]),
        ToolMessage(content=result, tool_call_id=call_id, name=tool, status=status),
    ]


def _req(messages: list | None = None) -> _FakeReq:
    messages = messages if messages is not None else [HumanMessage(content="task")]
    return _FakeReq(messages=messages, state={"messages": list(messages)})


async def _run(mw: LinsightCitationSourceMiddleware, req: _FakeReq) -> _FakeReq:
    captured: dict = {}

    async def handler(r):
        captured["req"] = r
        return "RESP"

    out = await mw.awrap_model_call(req, handler)
    assert out == "RESP"
    return captured["req"]


def _human_tail(req: _FakeReq, original_len: int) -> list[str]:
    tail = req.messages[original_len:]
    assert all(isinstance(m, HumanMessage) for m in tail)
    return [m.content for m in tail]


# --------------------------------------------------------------------------
# source table
# --------------------------------------------------------------------------
async def test_source_table_is_appended_as_last_message_and_state_untouched(fake_redis):
    scope = _scope(3)
    req = _req()
    state_before = list(req.state["messages"])

    seen = await _run(LinsightCitationSourceMiddleware(scope), req)

    assert len(seen.messages) == 2
    table = seen.messages[-1]
    assert isinstance(table, HumanMessage)
    lines = table.content.split("\n")
    assert lines[0] == SOURCE_TABLE_HEADER
    assert lines[1] == "S1 知识库·知识文档1（第1页）"
    assert lines[2] == "S2 网页·网页标题2"
    assert lines[3] == "S3 知识库·知识文档3（第3页）"
    assert SOURCE_TABLE_OVERFLOW_LINE not in table.content
    # graph state and the original request are untouched
    assert seen.state["messages"] == state_before
    assert req.state["messages"] == state_before
    assert len(req.messages) == 1


async def test_source_table_truncates_title_to_40_chars(fake_redis):
    scope = LinsightCitationScope(svid=SVID, session_id=SESSION_ID)
    scope.register_handle("S1", "k1", {"type": "temp", "title": "甲" * 60, "loc": ""})

    seen = await _run(LinsightCitationSourceMiddleware(scope), _req())

    assert seen.messages[-1].content.split("\n")[1] == "S1 知识库·" + "甲" * 40


@pytest.mark.parametrize("scope", [None, _scope(3, enabled=False), _scope(0)])
async def test_disabled_or_empty_scope_passes_through(fake_redis, scope):
    req = _req()

    seen = await _run(LinsightCitationSourceMiddleware(scope), req)

    assert seen is req


async def test_row_cap_keeps_latest_handles_and_adds_tail_line(fake_redis):
    scope = _scope(160)

    seen = await _run(LinsightCitationSourceMiddleware(scope), _req())

    lines = seen.messages[-1].content.split("\n")
    assert lines[0] == SOURCE_TABLE_HEADER
    assert lines[-1] == SOURCE_TABLE_OVERFLOW_LINE
    rows = lines[1:-1]
    assert len(rows) == 150
    assert rows[0].startswith("S11 ")
    assert rows[-1].startswith("S160 ")
    assert not any(r.startswith("S1 ") or r.startswith("S10 ") for r in rows)


async def test_custom_max_rows(fake_redis):
    seen = await _run(LinsightCitationSourceMiddleware(_scope(5), max_rows=2), _req())

    lines = seen.messages[-1].content.split("\n")
    assert lines[1:-1] == ["S4 网页·网页标题4", "S5 知识库·知识文档5（第5页）"]
    assert lines[-1] == SOURCE_TABLE_OVERFLOW_LINE


# --------------------------------------------------------------------------
# nudge
# --------------------------------------------------------------------------
async def test_nudge_emitted_for_uncited_output_md_and_logged(fake_redis, nudge_log):
    scope = _scope(3)
    messages = _write_turn("output/x.md", "# 报告\n\n正文没有编号。")
    req = _req(messages)

    seen = await _run(LinsightCitationSourceMiddleware(scope), req)

    tail = _human_tail(seen, len(messages))
    assert len(tail) == 2
    assert tail[0].startswith(SOURCE_TABLE_HEADER)
    assert tail[1].startswith("output/x.md 已写入成功，但正文没有来源编号。")
    assert "edit_file" in tail[1] and "[Sn]" in tail[1]
    # state untouched
    assert seen.state["messages"] == messages
    # dedupe recorded on the session handle table with the table's TTL
    assert fake_redis.set_calls == [
        {
            "name": handle_redis_key(SESSION_ID),
            "key": f"nudged:{SVID}:output/x.md",
            "value": "1",
            "expiration": HANDLE_TTL_SECONDS,
        }
    ]
    assert ("INFO", f"{NUDGE_LOG_PREFIX} session={SVID} file=output/x.md") in nudge_log


async def test_nudge_reads_state_messages_not_request_messages(fake_redis):
    """A wrap-up HumanMessage already appended to the request must not hide the write."""
    messages = _write_turn("output/x.md", "no handles")
    req = _FakeReq(messages=[*messages, HumanMessage(content="wrap up now")], state={"messages": list(messages)})

    seen = await _run(LinsightCitationSourceMiddleware(_scope(2)), req)

    assert any("output/x.md 已写入成功" in m.content for m in seen.messages)


async def test_nudge_accepts_leading_slash_and_uses_basename(fake_redis, nudge_log):
    messages = _write_turn("/output/sub/Final.MD", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(2)), _req(messages))

    tail = _human_tail(seen, len(messages))
    assert tail[1].startswith("output/Final.MD 已写入成功")
    assert ("INFO", f"{NUDGE_LOG_PREFIX} session={SVID} file=output/sub/Final.MD") in nudge_log


async def test_nudge_for_edit_file_uses_new_string(fake_redis):
    messages = _write_turn("output/x.md", "patched paragraph without handles", tool="edit_file")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(2)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 2


async def test_no_nudge_when_file_has_handles(fake_redis, nudge_log):
    messages = _write_turn("output/x.md", "根据资料，结论成立 [S3]。")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    tail = _human_tail(seen, len(messages))
    assert len(tail) == 1 and tail[0].startswith(SOURCE_TABLE_HEADER)
    assert fake_redis.set_calls == []
    assert not any(NUDGE_LOG_PREFIX in msg for _, msg in nudge_log)


async def test_no_nudge_twice_for_same_file_in_process(fake_redis, nudge_log):
    mw = LinsightCitationSourceMiddleware(_scope(3))
    messages = _write_turn("output/x.md", "no handles")

    first = await _run(mw, _req(messages))
    second = await _run(mw, _req(messages))

    assert len(_human_tail(first, len(messages))) == 2
    assert len(_human_tail(second, len(messages))) == 1
    assert len(fake_redis.set_calls) == 1
    assert sum(1 for _, msg in nudge_log if NUDGE_LOG_PREFIX in msg and "file=" in msg) == 1


async def test_no_nudge_when_redis_says_already_nudged(fake_redis):
    """A rebuilt instance (resume / continue) must honour the Redis record (design §5 #13)."""
    fake_redis.store[(handle_redis_key(SESSION_ID), f"nudged:{SVID}:output/x.md")] = "1"
    messages = _write_turn("output/x.md", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 1
    assert fake_redis.set_calls == []


async def test_no_nudge_during_soft_landing(fake_redis):
    sink = {"soft_landing": True}
    messages = _write_turn("output/x.md", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3), budget_sink=sink), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 1
    assert fake_redis.set_calls == []


async def test_no_nudge_for_subagent_instance(fake_redis):
    messages = _write_turn("output/x.md", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3), is_subagent=True), _req(messages))

    tail = _human_tail(seen, len(messages))
    assert len(tail) == 1 and tail[0].startswith(SOURCE_TABLE_HEADER)
    assert fake_redis.set_calls == []


@pytest.mark.parametrize(
    "status,result",
    [("error", "Error: disk full"), ("success", "Error: file exists"), ("error", "something went wrong")],
)
async def test_no_nudge_when_tool_result_is_error(fake_redis, status, result):
    messages = _write_turn("output/x.md", "no handles", status=status, result=result)

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 1


@pytest.mark.parametrize(
    "path", ["scratch/notes.md", "output/index.html", "output/data.txt", "report.md", "outputs/x.md"]
)
async def test_no_nudge_for_non_deliverable_paths(fake_redis, path):
    messages = _write_turn(path, "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 1


async def test_no_nudge_without_write_in_last_batch(fake_redis):
    messages = [
        *_write_turn("output/x.md", "no handles", call_id="call-w"),
        AIMessage(content="", tool_calls=[{"name": "ls", "args": {"path": "."}, "id": "call-ls", "type": "tool_call"}]),
        ToolMessage(content="output/x.md", tool_call_id="call-ls", name="ls"),
    ]

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 1


async def test_redis_failure_still_yields_table_and_nudge(monkeypatch, nudge_log):
    monkeypatch.setattr(mod, "get_redis_client", AsyncMock(return_value=_BrokenRedis()))
    messages = _write_turn("output/x.md", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    tail = _human_tail(seen, len(messages))
    assert len(tail) == 2
    assert tail[1].startswith("output/x.md 已写入成功")
    assert ("INFO", f"{NUDGE_LOG_PREFIX} session={SVID} file=output/x.md") in nudge_log


async def test_redis_client_unavailable_still_yields_table_and_nudge(monkeypatch):
    monkeypatch.setattr(mod, "get_redis_client", AsyncMock(side_effect=RuntimeError("no redis")))
    messages = _write_turn("output/x.md", "no handles")

    seen = await _run(LinsightCitationSourceMiddleware(_scope(3)), _req(messages))

    assert len(_human_tail(seen, len(messages))) == 2


async def test_preparation_error_passes_request_through(fake_redis):
    """Anything unexpected during preparation degrades to the untouched request; never raises."""

    class _Boom(list):
        def __iter__(self):
            raise RuntimeError("boom")

    scope = _scope(2)
    scope.entries = _Boom(scope.entries)
    req = _req()

    seen = await _run(LinsightCitationSourceMiddleware(scope), req)

    assert seen is req


async def test_handler_exception_propagates(fake_redis):
    mw = LinsightCitationSourceMiddleware(_scope(2))

    async def handler(r):
        raise ValueError("model failed")

    with pytest.raises(ValueError):
        await mw.awrap_model_call(_req(), handler)


# --------------------------------------------------------------------------
# sync hook / identity
# --------------------------------------------------------------------------
def test_sync_hook_appends_table_and_nudge_without_redis(monkeypatch, nudge_log):
    monkeypatch.setattr(
        mod, "get_redis_client", AsyncMock(side_effect=AssertionError("sync path must not touch Redis"))
    )
    mw = LinsightCitationSourceMiddleware(_scope(3))
    messages = _write_turn("output/x.md", "no handles")
    captured: dict = {}

    def handler(r):
        captured["req"] = r
        return "RESP"

    assert mw.wrap_model_call(_req(messages), handler) == "RESP"
    assert len(_human_tail(captured["req"], len(messages))) == 2
    # in-process dedupe still applies on the sync path
    assert mw.wrap_model_call(_req(messages), handler) == "RESP"
    assert len(_human_tail(captured["req"], len(messages))) == 1


def test_registers_no_tools_and_has_distinct_names():
    main = LinsightCitationSourceMiddleware(_scope(1))
    sub = LinsightCitationSourceMiddleware(_scope(1), is_subagent=True)

    assert main.tools == [] and sub.tools == []
    assert main.name == "LinsightCitationSource"
    assert sub.name == "LinsightCitationSourceSub"
    assert main.name != sub.name
    assert not hasattr(LinsightCitationSourceMiddleware, "wrap_tool_call") or (
        LinsightCitationSourceMiddleware.wrap_tool_call is mod.AgentMiddleware.wrap_tool_call
    )

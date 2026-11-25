"""F004 (T055 leftover): tool display data and complete tool output of a ``direct`` run.

* the runner puts ``display_name`` / ``tool_type`` (``chat_service._build_tool_meta``)
  on the main-graph ``tool_call`` events, so the answer row and the legacy SSE
  frames no longer fall back to the raw defaults;
* the stream keeps tool output cut at 8000 characters, while the event hooks
  (the answer row) receive the complete output.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from bisheng.linsight.domain.schemas import run_events
from bisheng.workstation.domain.services import chat_service
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector
from bisheng.workstation.domain.services.run_send import LegacyFrameTranslator
from test.workstation.run_persist_support import MessageTable
from test.workstation.test_direct_run import CID, USER, _call, echo, make_env  # noqa: F401

LONG = "长" * 9000


@tool
def web_search(query: str) -> str:
    """Search the web."""
    return LONG


@tool
def search_knowledge_bases(query: str) -> str:
    """Search the selected knowledge bases."""
    return "知识库片段"


def _tool_calls(events: list[dict], name: str) -> list[dict]:
    return [e["data"] for e in events if e["type"] == "tool_call" and e["data"]["name"] == name]


async def _run(make_env, monkeypatch, script: list[Any], tools: list) -> tuple[Any, MessageTable]:  # noqa: F811
    table = MessageTable().install(monkeypatch)

    async def no_citations(**_: Any) -> None:
        return None

    monkeypatch.setattr(chat_service, "save_message_citations", no_citations)
    env = make_env(script, tools)
    ctx = await env.submit("查一下")
    projector = DirectRunProjector(run_id=ctx.run_id, conversation_id=CID, user_id=USER, sender="model")
    env.hook = projector.on_event
    assert (await env.run(ctx)).status == "finished"
    return env, table


async def test_tool_events_carry_display_name_and_type(make_env, monkeypatch):  # noqa: F811
    env, table = await _run(
        make_env,
        monkeypatch,
        [
            _call("search_knowledge_bases", {"query": "制度"}, "k1"),
            _call("web_search", {"query": "新闻"}, "w1"),
            _call("echo", {"text": "hi"}, "e1"),
            AIMessage(content="查到了"),
        ],
        [search_knowledge_bases, web_search, echo],
    )
    events = await env.events()

    for name, tool_type in (("search_knowledge_bases", "knowledge"), ("web_search", "web"), ("echo", "tool")):
        frames = _tool_calls(events, name)
        assert [f["status"] for f in frames] == ["start", "end"]
        for frame in frames:
            assert frame["extra_info"]["display_name"] == name
            assert frame["extra_info"]["tool_type"] == tool_type

    # The stored answer row uses them ...
    (row,) = table.answers()
    stored = {e["tool_name"]: e for e in json.loads(row.message)["events"] if e["type"] == "tool_call"}
    assert {name: e["tool_type"] for name, e in stored.items()} == {
        "search_knowledge_bases": "knowledge",
        "web_search": "web",
        "echo": "tool",
    }
    # ... and so do the legacy frames, which are built from the stream alone.
    translator = LegacyFrameTranslator(CID)
    frames = [frame for event in events for frame in translator.feed(event)]
    payloads = [json.loads(f.split("data: ", 1)[1]) for f in frames if '"agent_tool_call"' in f]
    types = {(p["message"]["tool_name"], p["message"]["tool_type"]) for p in payloads}
    assert types == {("search_knowledge_bases", "knowledge"), ("web_search", "web"), ("echo", "tool")}


async def test_row_stores_complete_tool_output_while_events_stay_truncated(make_env, monkeypatch):  # noqa: F811
    env, table = await _run(
        make_env,
        monkeypatch,
        [_call("web_search", {"query": "新闻"}, "w1"), AIMessage(content="查到了")],
        [web_search],
    )

    (end,) = [f for f in _tool_calls(await env.events(), "web_search") if f["status"] == "end"]
    # The stream: cut at 8000 characters and flagged.
    assert len(end["output"]) == 8001 and end["extra_info"]["truncated"] is True

    # The answer row: the complete result, as the legacy daily chat stores it.
    (row,) = table.answers()
    (stored,) = [e for e in json.loads(row.message)["events"] if e["type"] == "tool_call"]
    assert json.dumps(stored["results"], ensure_ascii=False).count("长") == 9000


def test_translator_and_projector_fall_back_to_the_tool_name():
    """An event written by a node that runs the older code has no display data."""
    event = run_events.make_event(
        run_events.TOOL_CALL, {"call_id": "c1", "name": "echo", "status": "start", "params": {}}, run_id="r"
    )
    (frame,) = LegacyFrameTranslator(CID).feed(event)
    message = json.loads(frame.split("data: ", 1)[1])["message"]

    assert (message["display_name"], message["tool_type"]) == ("echo", "tool")

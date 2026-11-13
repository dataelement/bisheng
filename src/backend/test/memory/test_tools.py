"""Model tools and tool-event redaction (AC-09, AC-14, AC-57, AC-61)."""

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from bisheng.common.errcode.memory import MemoryContentSensitiveError
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.redaction import (
    is_memory_tool,
    is_memory_tool_output,
    redact_tool_event,
    replay_placeholder,
    split_reserved_tools,
)
from bisheng.memory.domain.services.search import SEARCH_HEADER, SearchService
from bisheng.memory.domain.services.tools import build_memory_tools
from bisheng.memory.domain.services.turn_record import TurnRecordService
from test.memory.conftest import counter


@pytest.fixture
def tools_for(service, index, details, kv):
    search = SearchService(index=index, details=details, metrics=m.MemoryMetrics(kv))

    def _build(ctx, **kw):
        return {t.name: t for t in build_memory_tools(ctx, service=service, search=search, **kw)}

    return _build


def test_two_tools_with_today_in_user_timezone(tools_for, make_ctx):
    tools = tools_for(make_ctx(timezone="America/New_York"))
    assert set(tools) == {"memory_write", "memory_search"}
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    desc = tools["memory_write"].description
    assert today in desc and "明确要求" in desc


def test_bad_timezone_falls_back_to_default(tools_for, make_ctx):
    tools = tools_for(make_ctx(timezone="Nowhere/Zone"))
    assert datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d") in tools["memory_write"].description


async def test_write_actions_call_service(tools_for, make_ctx, service):
    ctx = make_ctx()
    written = []
    tools = tools_for(ctx, on_write=written.append)
    out = json.loads(
        await tools["memory_write"].ainvoke({"action": "remember", "content": "用户偏好中文回答", "type": "preference"})
    )
    assert out["ok"] is True and out["item_id"] and out["op"] == "remember"
    out2 = json.loads(
        await tools["memory_write"].ainvoke(
            {"action": "correct", "content": "用户偏好英文回答", "target_id": out["item_id"]}
        )
    )
    assert out2["ok"] and out2["related_item_id"] == out["item_id"]
    out3 = json.loads(await tools["memory_write"].ainvoke({"action": "forget", "target_id": out2["item_id"]}))
    assert out3["ok"]
    assert [w.op for w in written] == ["remember", "correct", "forget"]
    assert ctx.extra.get("memory_written") is True
    assert await service.list(ctx) == []


async def test_ac14_rejected_write_returns_reason_code(tools_for, make_ctx):
    tools = tools_for(make_ctx())
    out = json.loads(
        await tools["memory_write"].ainvoke({"action": "remember", "content": "用户明天要出差", "type": "fact"})
    )
    assert out["ok"] is False and out["reason_code"] == 12102
    out = json.loads(
        await tools["memory_write"].ainvoke({"action": "remember", "content": "密码是 abc12345", "type": "fact"})
    )
    assert out["reason_code"] == MemoryContentSensitiveError.Code


async def test_ac57_search_records_and_prefixes(tools_for, make_ctx, service):
    ctx = make_ctx(turn_id="t-s")
    res = await service.write(make_ctx(turn_id="t0"), "remember", content="用户的项目叫北极星", type="fact")
    out = await tools_for(ctx)["memory_search"].ainvoke({"query": "北极星项目"})
    assert out.startswith(SEARCH_HEADER)
    assert datetime.now().strftime("%Y-%m-%d") in out and res.item_id in out
    view = await TurnRecordService.get_for_owner(ctx, turn_id="t-s")
    assert view["retrieved_item_ids"] == [res.item_id]
    assert ctx.extra.get("memory_retrieved") is True


async def test_ac61_search_unavailable_returns_message_not_raise(tools_for, make_ctx, index, kv):
    ctx = make_ctx()
    index.keyword_down = index.vector_down = True
    out = await tools_for(ctx)["memory_search"].ainvoke({"query": "x"})
    assert "不可用" in out
    assert await counter(kv, ctx.tenant_id, m.SEARCH_FAILED) == 1


def test_ac09_redaction_of_memory_tools_only():
    args = {"action": "remember", "content": "用户的秘密", "type": "fact"}
    result = json.dumps({"ok": True, "op": "remember", "item_id": "i-1"})
    assert redact_tool_event("memory_write", args) == {"redacted": True, "op": "remember", "item_ids": []}
    assert redact_tool_event("memory_write", result) == {
        "redacted": True, "op": "remember", "item_ids": ["i-1"], "ok": True, "reason_code": None
    }
    search_out = SEARCH_HEADER + "\n- id=i-2 [事实] 用户的秘密（记录于 2026-11-13）"
    red = redact_tool_event("memory_search", search_out)
    assert red == {"redacted": True, "op": "search", "item_ids": ["i-2"], "ok": True, "reason_code": None}
    assert "秘密" not in json.dumps(red, ensure_ascii=False)
    assert redact_tool_event("web_search", args) is args
    assert redact_tool_event("memory_search", {}) == {"redacted": True, "op": "search", "item_ids": []}


def test_replay_placeholder_and_output_marker():
    assert replay_placeholder() == "记忆操作已完成"
    assert is_memory_tool_output(SEARCH_HEADER + "\n...")
    assert is_memory_tool_output(json.dumps({"memory_tool": "memory_write", "ok": True}))
    assert not is_memory_tool_output("ordinary tool output")


def test_reserved_name_conflict_detected():
    ext = [SimpleNamespace(name="memory_write"), SimpleNamespace(name="web_search"), SimpleNamespace(name="memory_x")]
    kept, dropped = split_reserved_tools(ext)
    assert [t.name for t in kept] == ["web_search"]
    assert [t.name for t in dropped] == ["memory_write", "memory_x"]
    # Reserved prefix for author tools, but redaction only covers the two built-in tools.
    from bisheng.memory.domain.services.redaction import is_reserved_tool_name

    assert is_reserved_tool_name("memory_anything") and not is_reserved_tool_name("mymemory")
    assert is_memory_tool("memory_write") and is_memory_tool("memory_search")
    assert not is_memory_tool("memory_store")


def test_third_party_memory_prefixed_tool_is_not_redacted():
    """AC-09 scope: an MCP tool named memory_store keeps its input and output."""
    payload = {"key": "k", "value": "v"}
    assert redact_tool_event("memory_store", payload) is payload


async def test_ac61_unexpected_search_error_is_returned_not_raised(tools_for, make_ctx, monkeypatch):
    """AC-61: any search failure comes back to the model as text; the agent loop never sees an exception."""
    ctx = make_ctx()

    async def _boom(*a, **k):
        raise RuntimeError("database gone")

    from bisheng.memory.domain.services import search as search_mod

    monkeypatch.setattr(search_mod.SearchService, "search", _boom)
    out = await tools_for(ctx)["memory_search"].ainvoke({"query": "x"})
    assert "不可用" in out


def test_ac09_redacted_output_keeps_status_without_content():
    """A rejected write keeps ok/reason_code so the UI can say why; no text survives."""
    rejected = json.dumps(
        {"memory_tool": "memory_write", "op": "remember", "ok": False, "reason_code": 12102, "reason": "用户明天出差"},
        ensure_ascii=False,
    )
    red = redact_tool_event("memory_write", rejected)
    assert red == {"redacted": True, "op": "remember", "item_ids": [], "ok": False, "reason_code": 12102}
    assert "明天" not in json.dumps(red, ensure_ascii=False)
    # Already-redacted payloads pass their status through unchanged.
    assert redact_tool_event("memory_write", red) == red
    down = redact_tool_event("memory_search", "记忆检索暂时不可用。请在回答中说明这一点。")
    assert down["ok"] is False and down["reason_code"] == 12107

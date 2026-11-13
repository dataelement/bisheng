"""F132 T060: the workflow ``memory_retriever`` node.

Covers AC-02, AC-28, AC-57, AC-60, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83,
AC-84, AC-86. The node is synchronous; async tests seed memory and then run it
in a worker thread, the way Celery runs it. The two read-only ``graph_state``
fields (``chat_id``, ``memory_enabled``) are set directly in these tests.
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import pytest
from sqlmodel import select

from bisheng.common.errcode.memory import MemorySearchLimitInvalidError, MemorySearchUnavailableError
from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
from bisheng.memory.domain.ports import SCENE_ASSISTANT, SCENE_DAILY, MemoryContext
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.graph.graph_engine import GraphEngine
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.node_manage import NodeFactory
from test.workflow.memory_fixtures import (  # noqa: F401  (fixtures)
    TENANT_A,
    USER_1,
    USER_2,
    details,
    graph,
    index,
    kv,
    memory_db,
    memory_runtime_config,
    register_chat,
    retriever_node,
    service,
    wired,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]
PREFIX = re.compile(r"^［背景信息，记录于 \d{4}-\d{2}-\d{2}］")
CHAT = "wf-chat-1"


class RecordingCallback(BaseCallback):
    def __init__(self):
        self.ends = []

    def on_node_end(self, data):
        self.ends.append(data)


def _ctx(user_id=USER_1, scene=SCENE_DAILY, **kw) -> MemoryContext:
    kw.setdefault("chat_id", "src-chat")
    kw.setdefault("turn_id", "seed-turn")
    return MemoryContext(tenant_id=TENANT_A, user_id=user_id, timezone="Asia/Shanghai", scene=scene, **kw)


def _node(
    query="喜欢川菜", limit=20, chat_id=CHAT, enabled=True, state=None, callback=None, node_id="mr_1", user_id=USER_1
):
    data = retriever_node(node_id=node_id, query=query, limit=limit)["data"]
    state = state or GraphState(chat_id=chat_id, memory_enabled=enabled)
    return NodeFactory.instance_node(
        NodeType.MEMORY_RETRIEVER.value,
        node_data=BaseNodeData(**data),
        workflow_id="wf-1",
        workflow_name="报销流程",
        user_id=user_id,
        graph_state=state,
        target_edges=[],
        max_steps=10,
        callback=callback or BaseCallback(),
    )


def _body(item: dict) -> str:
    return item["text"].split("］", 1)[1]


async def _run(node) -> list[dict]:
    """Run like the Celery worker: synchronous node in a thread without a running loop."""
    await asyncio.to_thread(node.run, {})
    return node.graph_state.get_variable(node.id, "retrieved_memory")


# ---- AC-78 ------------------------------------------------------------------------------


def test_ac78_node_type_registered():
    """AC-78: the node type exists and is registered in the node factory."""
    assert NodeType.MEMORY_RETRIEVER.value == "memory_retriever"
    assert NodeFactory.get_node_class("memory_retriever") is not None


def test_ac78_ac83_several_nodes_in_one_workflow():
    """AC-78, AC-83: two retriever nodes in one graph; no session (debug run) -> both output []."""
    engine = GraphEngine(
        user_id=None,
        workflow_id="wf-1",
        workflow_name="多节点",
        workflow_data=graph(
            retriever_node("mr_1", query="出差"), retriever_node("mr_2", query="报销"), memory_enabled=True
        ),
        async_mode=False,
        max_steps=10,
        callback=BaseCallback(),
    )
    engine.run()
    assert engine.status == "SUCCESS", engine.reason
    assert engine.graph_state.get_variable("mr_1", "retrieved_memory") == []
    assert engine.graph_state.get_variable("mr_2", "retrieved_memory") == []


# ---- AC-79 query ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "variables", "expected"),
    [
        ("我喜欢什么菜", {}, "我喜欢什么菜"),
        ("{{#input_1.q#}}", {"q": "川菜"}, "川菜"),
        ("用户问：{{#input_1.q#}}，请找偏好", {"q": "川菜"}, "用户问：川菜，请找偏好"),
        ("{{#input_1.q#}}", {"q": {"城市": "成都", "n": 2}}, '{"城市": "成都", "n": 2}'),
        ("{{#input_1.q#}}", {"q": ["a", "b"]}, '["a", "b"]'),
        ("数量 {{#input_1.q#}}", {"q": 3}, "数量 3"),
    ],
)
def test_ac79_query_text_variable_and_mixed(query, variables, expected):
    """AC-79: literal text, a variable reference or both; non-text values become text."""
    state = GraphState(chat_id="", memory_enabled=False)
    for k, v in variables.items():
        state.set_variable("input_1", k, v)
    node = _node(query=query, state=state)
    node.run({})
    log = node.parse_log("x", {"retrieved_memory": []})
    assert log[0][0]["value"] == expected


# ---- AC-80 limit ------------------------------------------------------------------------


def test_ac80_limit_defaults_to_20():
    """AC-80: missing limit means 20."""
    from bisheng.workflow.nodes.memory_retriever.memory_retriever import parse_limit

    assert parse_limit(None) == 20
    node = _node(limit=..., enabled=False)
    assert node.limit == 20


@pytest.mark.parametrize("value", [1, 20, 100, "50", 30.0])
def test_ac80_limit_accepts_integers_1_to_100(value):
    """AC-80: integers from 1 to 100 are accepted."""
    from bisheng.workflow.nodes.memory_retriever.memory_retriever import parse_limit

    assert parse_limit(value) == int(float(value))


@pytest.mark.parametrize("value", [0, 101, -3, 2.5, "abc", "", True, [5]])
def test_ac80_limit_rejects_out_of_range_and_non_integers(value):
    """AC-80: anything else is refused with the limit-invalid error code (12108)."""
    from bisheng.workflow.nodes.memory_retriever.memory_retriever import parse_limit

    with pytest.raises(MemorySearchLimitInvalidError) as exc:
        parse_limit(value)
    assert exc.value.code == 12108
    with pytest.raises(MemorySearchLimitInvalidError):
        _node(limit=value)


# ---- AC-81 / AC-02 search scope and order -------------------------------------------------


async def test_ac81_own_memory_any_scene_ranked_and_limited(memory_db, wired):
    """AC-81: only the user's own active items, from any scene, most relevant first, at most limit."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜和火锅川菜", type="preference")
    await wired.service.write(
        _ctx(scene=SCENE_ASSISTANT, app_id="asst-1", app_name="差旅助手"),
        "remember",
        content="用户喜欢川菜",
        type="preference",
    )
    await wired.service.write(_ctx(), "remember", content="用户喜欢喝茶", type="preference")
    await wired.service.write(_ctx(user_id=USER_2), "remember", content="乙喜欢川菜", type="preference")

    out = await _run(_node(query="喜欢川菜火锅"))
    bodies = [_body(o) for o in out]
    assert bodies == ["用户喜欢川菜和火锅川菜", "用户喜欢川菜", "用户喜欢喝茶"]
    assert out[1]["metadata"]["source"]["app_name"] == "差旅助手"
    assert all(o["metadata"]["source"]["scene"] in (SCENE_DAILY, SCENE_ASSISTANT) for o in out)
    assert "乙喜欢川菜" not in str(out)

    out = await _run(_node(query="喜欢川菜火锅", limit=1, node_id="mr_2"))
    assert [_body(o) for o in out] == ["用户喜欢川菜和火锅川菜"]


async def test_ac02_two_users_same_workflow_see_only_their_own(memory_db, wired):
    """AC-02: two users run the same workflow; each gets only their own items."""
    register_chat(memory_db, "chat-u1", user_id=USER_1)
    register_chat(memory_db, "chat-u2", user_id=USER_2)
    await wired.service.write(_ctx(USER_1), "remember", content="甲的成本中心是 C-100", type="fact")
    await wired.service.write(_ctx(USER_2), "remember", content="乙的成本中心是 C-200", type="fact")

    out1 = await _run(_node(query="成本中心", chat_id="chat-u1"))
    out2 = await _run(_node(query="成本中心", chat_id="chat-u2", user_id=USER_2))
    assert [_body(o) for o in out1] == ["甲的成本中心是 C-100"]
    assert [_body(o) for o in out2] == ["乙的成本中心是 C-200"]


# ---- AC-82 / AC-57 output shape -----------------------------------------------------------


async def test_ac82_ac57_output_fields_prefix_and_detail(memory_db, wired):
    """AC-82, AC-57: content, type, recorded time, source, event time; detail text replaces content;
    every text starts with the background prefix and the recorded date."""
    register_chat(memory_db, CHAT)
    await wired.service.write(
        _ctx(),
        "remember",
        content="季度复盘结论：先对齐口径",
        type="experience",
        event_time="2026-12-01",
        detail="季度复盘全文：第一，先对齐口径；第二，再拆目标。",
    )
    await wired.service.write(_ctx(), "remember", content="季度复盘由财务部牵头", type="fact")

    items = await _run(_node(query="季度复盘"))
    assert len(items) == 2
    out = {"detail" if o["metadata"]["type"] == "experience" else "plain": o for o in items}
    for o in out.values():
        assert PREFIX.match(o["text"]), o["text"]
        meta = o["metadata"]
        assert set(meta) >= {"type", "recorded_at", "event_time", "source"}
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["recorded_at"])
        assert o["text"].startswith(f"［背景信息，记录于 {meta['recorded_at']}］")
        assert meta["source"]["scene"] == SCENE_DAILY and meta["source"]["origin"] == "explicit"

    d = out["detail"]
    assert d["text"].endswith("季度复盘全文：第一，先对齐口径；第二，再拆目标。")
    assert "季度复盘结论：先对齐口径" not in d["text"]
    assert d["metadata"]["type"] == "experience" and d["metadata"]["event_time"] == "2026-12-01"

    p = out["plain"]
    assert p["text"].endswith("季度复盘由财务部牵头")
    assert p["metadata"]["type"] == "fact" and p["metadata"]["event_time"] is None


async def test_ac82_detail_read_failure_falls_back_to_content(memory_db, wired):
    """AC-82: when the detail object cannot be read the item still comes back with its content."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="差旅标准：一线城市 600", type="fact", detail="全文")
    wired.details.read_fail = True
    out = await _run(_node(query="差旅标准"))
    assert len(out) == 1 and out[0]["text"].endswith("差旅标准：一线城市 600")


# ---- AC-83 empty cases ------------------------------------------------------------------


async def test_ac83_no_hit_gives_empty_list(memory_db, wired):
    """AC-83: nothing matches -> [] and the node finishes normally."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    cb = RecordingCallback()
    assert await _run(_node(query="量子力学", callback=cb)) == []
    assert cb.ends[-1].reason is None


async def test_ac83_empty_runtime_query_gives_empty_list(memory_db, wired):
    """AC-83: the query resolves to empty text at run time -> [] without searching."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    state = GraphState(chat_id=CHAT, memory_enabled=True)
    state.set_variable("input_1", "q", "   ")
    before = len(wired.index.filters)
    assert await _run(_node(query="{{#input_1.q#}}", state=state)) == []
    assert len(wired.index.filters) == before


@pytest.mark.parametrize("case", ["no_registration", "my_memory_off", "workflow_switch_off", "no_chat_id"])
async def test_ac83_not_enabled_gives_empty_list(memory_db, wired, case):
    """AC-83 / AC-10: unregistered session, "my memory" off, workflow switch off, or no chat_id -> []."""
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    chat_id, enabled = CHAT, True
    if case != "no_registration":
        register_chat(memory_db, CHAT)
    if case == "my_memory_off":
        await SettingRepository.set_enabled(_ctx(), False)
    if case == "workflow_switch_off":
        enabled = False
    if case == "no_chat_id":
        chat_id = ""
    cb = RecordingCallback()
    assert await _run(_node(chat_id=chat_id, enabled=enabled, callback=cb)) == []
    assert cb.ends[-1].reason is None


# ---- AC-84 failure ----------------------------------------------------------------------


async def test_ac84_search_unavailable_fails_the_node(memory_db, wired):
    """AC-84: both search paths down -> the node fails with a reason, never an empty list."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    wired.index.keyword_down = True
    cb = RecordingCallback()
    node = _node(callback=cb)
    with pytest.raises(MemorySearchUnavailableError):
        await asyncio.to_thread(node.run, {})
    assert cb.ends[-1].reason
    assert node.graph_state.get_variable(node.id, "retrieved_memory") is None


# ---- AC-86 log --------------------------------------------------------------------------


async def test_ac86_log_has_query_and_count_but_no_content(memory_db, wired):
    """AC-86: the run log records the query and the number of items, never item text."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜馆子", type="preference")
    cb = RecordingCallback()
    out = await _run(_node(query="喜欢川菜", callback=cb))
    log = cb.ends[-1].log_data
    flat = {entry["key"]: entry["value"] for round_ in log for entry in round_}
    assert len(out) == 2
    assert flat == {"mr_1.query": "喜欢川菜", "mr_1.retrieved_count": 2}
    assert "用户喜欢川菜" not in str(log)


# ---- no turn records, no resident injection, no write ability -----------------------------


async def test_node_writes_no_turn_record(memory_db, wired):
    """The retriever node only reads: it never writes a turn record (workflow has no attribution)."""
    register_chat(memory_db, CHAT)
    await wired.service.write(_ctx(), "remember", content="用户喜欢川菜", type="preference")
    with memory_db.session() as s:
        before = len(s.exec(select(MemoryTurnRecord)).all())
    out = await _run(_node())
    assert out
    with memory_db.session() as s:
        assert len(s.exec(select(MemoryTurnRecord)).all()) == before


def _workflow_sources() -> list[pathlib.Path]:
    roots = [BACKEND / "bisheng" / "workflow", BACKEND / "bisheng" / "worker" / "workflow"]
    return [p for r in roots for p in r.rglob("*.py")]


def test_ac60_no_resident_memory_in_workflow():
    """AC-60: no workflow code path injects the resident block; only the retriever node reads memory."""
    for path in _workflow_sources():
        text = path.read_text(encoding="utf-8")
        assert "get_resident_service" not in text and "ResidentService" not in text, path
        assert ".experience(" not in text, path


def test_ac28_no_memory_write_ability_in_workflow():
    """AC-28: workflow runs offer no memory_write tool and never call the write service."""
    for path in _workflow_sources():
        text = path.read_text(encoding="utf-8")
        assert "build_memory_tools" not in text and "memory_write" not in text, path
        assert "get_memory_service" not in text, path


async def test_ac02_running_another_users_chat_gets_nothing(memory_db, wired):
    """AC-02: a run whose user is not the owner of the registered chat gets no memory."""
    register_chat(memory_db, "chat-u2", user_id=USER_2)
    await wired.service.write(_ctx(USER_2), "remember", content="乙的成本中心是 C-200", type="fact")
    assert await _run(_node(query="成本中心", chat_id="chat-u2", user_id=USER_1)) == []

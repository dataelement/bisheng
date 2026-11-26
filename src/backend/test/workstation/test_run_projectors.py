"""F004 T029: the two persistence projectors that consume unified run events.

``direct``: at run end the answer row is the one daily chat writes today
(``build_daily_answer_row`` + ``save_message_citations`` +
``_promote_generated_files``), plus the run id in ``extra``.
``planned``: plan rows go into ``linsight_execute_task`` with column-level
UPDATEs, throttled, never reading a whole row back.

No database, no Redis, no LLM: the DAOs are in-memory fakes and the plan events
come from the real ``StreamEventMapper`` + ``UnifiedEventOutput``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum, LinsightExecuteTask
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import run_projector_planned as planned_module
from bisheng.linsight.domain.services.run_projector_planned import PlannedRunProjector, load_plan
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper, UnifiedEventOutput
from bisheng.workstation.domain.services import chat_service
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

RUN_ID = "run-1"
CHAT_ID = "conv-1"
SVID = "sv-projector"


def _ev(event_type: str, data: dict | None = None, ts: int | None = None) -> dict:
    event = run_events.make_event(event_type, data, run_id=RUN_ID)
    if ts is not None:
        event["ts"] = ts
    return event


# ------------------------------------------------------------------ direct


class _MessageStore:
    """Stands in for ChatMessageDao and the citation / attachment writers."""

    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.citations: list[dict] = []
        self.promoted: list[dict] = []

    async def ainsert_one(self, row):
        row.id = 100 + len(self.rows)
        self.rows.append(row)
        return row

    async def save_message_citations(self, **kwargs):
        self.citations.append(kwargs)

    async def promote(self, files, user_id, *, storage_partition=None):
        for item in files:
            item["object_name"] = f"chat/{storage_partition}/{item['file_name']}"
        self.promoted.append({"user_id": user_id, "storage_partition": storage_partition, "files": files})


@pytest.fixture
def store(monkeypatch):
    store = _MessageStore()
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", store.ainsert_one)
    monkeypatch.setattr(chat_service, "save_message_citations", store.save_message_citations)
    monkeypatch.setattr(chat_service, "promote_chat_attachments", store.promote)

    async def _cited(items, text):
        return [item for item in items if item["id"] in text]

    monkeypatch.setattr(chat_service, "select_cited_items", _cited)
    return store


def _code_tool(entries: list[dict]):
    executor = SimpleNamespace(collect_deliverables=True, published_deliverables=entries)
    return SimpleNamespace(name="bisheng_code_interpreter", description="code", executor=executor)


def _direct(**overrides) -> DirectRunProjector:
    kwargs: dict[str, Any] = {
        "run_id": RUN_ID,
        "conversation_id": CHAT_ID,
        "user_id": 7,
        "sender": "DeepSeek",
        "tool_meta": {"web_search": {"display_name": "联网搜索", "tool_type": "web"}},
    }
    kwargs.update(overrides)
    return DirectRunProjector(**kwargs)


async def test_direct_answer_row_shape_unchanged(store):
    tools = [_code_tool([{"path": "output/a.csv", "name": "a.csv", "size": 3, "url": "http://h/tmp/a.csv?sig"}])]
    citations = [{"id": "[citation:k1]"}, {"id": "[citation:never-cited]"}]
    persisted: list[Any] = []

    async def on_persisted(row):
        persisted.append(row)

    projector = _direct(
        tools=tools,
        promote_user_id=7,
        storage_partition="7",
        citation_items=lambda: citations,
        on_persisted=on_persisted,
    )
    for event in [
        _ev(run_events.RUN_STARTED),
        _ev(run_events.THINKING, {"text": "先", "call_id": "th-1"}, ts=1000),
        _ev(run_events.THINKING, {"text": "搜一下", "call_id": "th-1"}, ts=1100),
        _ev(
            run_events.TOOL_CALL,
            {"call_id": "c1", "name": "web_search", "status": "start", "params": {"query": "毕昇"}},
            ts=1500,
        ),
        _ev(
            run_events.TOOL_CALL,
            {"call_id": "c1", "name": "web_search", "status": "end", "output": '[{"title": "毕昇"}]'},
            ts=1900,
        ),
        _ev(run_events.TEXT, {"text": "毕昇是"}, ts=2000),
        _ev(run_events.TEXT, {"text": "平台[citation:k1]"}, ts=2100),
        _ev(run_events.RUN_FINISHED, ts=2200),
    ]:
        await projector.on_event(event)
    await projector.aclose()

    assert len(store.rows) == 1
    row = store.rows[0]
    content = json.loads(row.message)
    expected_events = [
        {"type": "thinking", "content": "先搜一下", "started_at": 1000, "duration_ms": 500, "ended_at": 1500},
        {
            "type": "tool_call",
            "tool_call_id": "c1",
            "tool_name": "web_search",
            "display_name": "联网搜索",
            "tool_type": "web",
            "args": {"query": "毕昇"},
            "started_at": 1500,
            "results": [{"title": "毕昇"}],
            "error": None,
            "ended_at": 1900,
            "duration_ms": 400,
        },
        {"type": "text", "content": "毕昇是平台[citation:k1]"},
    ]
    assert content == {"msg": "毕昇是平台[citation:k1]", "events": expected_events}

    # Every column but ``extra`` equals what daily chat's own builder produces.
    today = chat_service.build_daily_answer_row(
        user_id=7,
        chat_id=CHAT_ID,
        sender="DeepSeek",
        db_content=content,
        files=json.loads(row.files),
    )
    for column in ("category", "type", "is_bot", "flow_id", "chat_id", "user_id", "sender", "source", "message"):
        assert getattr(row, column) == getattr(today, column), column
    assert row.files == today.files
    assert (row.category, row.type) == ("agent_answer", "end")

    files = json.loads(row.files)
    assert [(f["file_name"], f["path"], f["source"]) for f in files] == [
        ("a.csv", "output/a.csv", chat_service.GENERATED_FILE_SOURCE)
    ]
    assert files[0]["object_name"] == "chat/7/a.csv"
    assert store.promoted[0]["user_id"] == 7

    # Only the sources the answer cites are bound, to the saved row.
    assert store.citations == [
        {"message_id": row.id, "items": [{"id": "[citation:k1]"}], "chat_id": CHAT_ID, "flow_id": ""}
    ]
    assert json.loads(row.extra) == {"run_id": RUN_ID}
    assert projector.message_id == row.id
    assert persisted == [row]


async def test_direct_takes_streamed_args_from_the_end_frame(store):
    # A streamed tool call starts with empty params; the end frame carries them.
    projector = _direct()
    for event in [
        _ev(run_events.RUN_STARTED),
        _ev(run_events.TOOL_CALL, {"call_id": "w1", "name": "write_file", "status": "start", "params": {}}, ts=1000),
        _ev(
            run_events.TOOL_CALL,
            {
                "call_id": "w1",
                "name": "write_file",
                "status": "end",
                "params": {"file_path": "output/a.md", "content": "# A"},
                "output": "Updated file /output/a.md",
            },
            ts=1500,
        ),
        _ev(run_events.TEXT, {"text": "done"}, ts=1600),
        _ev(run_events.RUN_FINISHED, ts=1700),
    ]:
        await projector.on_event(event)
    await projector.aclose()

    calls = [e for e in json.loads(store.rows[0].message)["events"] if e["type"] == "tool_call"]
    assert calls[0]["args"] == {"file_path": "output/a.md", "content": "# A"}


async def test_direct_partial_saved_on_stop(store):
    projector = _direct()
    for event in [
        _ev(run_events.RUN_STARTED),
        _ev(run_events.TEXT, {"text": "写到一"}, ts=1000),
        _ev(run_events.TOOL_CALL, {"call_id": "c9", "name": "web_search", "status": "start", "params": {}}, ts=1200),
        _ev(run_events.RUN_STOPPED, {"reason": "user"}, ts=1500),
    ]:
        await projector.on_event(event)
    # A late event or the teardown must not write a second row.
    await projector.on_event(_ev(run_events.TEXT, {"text": "半"}))
    await projector.aclose()

    assert len(store.rows) == 1
    row = store.rows[0]
    content = json.loads(row.message)
    assert content["msg"] == "写到一"
    assert content["events"][0] == {"type": "text", "content": "写到一"}
    # The tool call that never ended is closed, so it does not render as running.
    tool = content["events"][1]
    assert tool["ended_at"] == 1500 and tool["duration_ms"] == 300 and tool["results"] == []
    assert tool["error"] == "stopped by user"
    # A user stop has its own mark and is not an error row (design §7 item 2).
    assert json.loads(row.extra) == {"status": "stopped", "run_id": RUN_ID}
    assert row.category == "agent_answer" and row.type == "end"


async def test_direct_failed_run_keeps_error_card_fields(store):
    projector = _direct()
    await projector.on_event(_ev(run_events.TEXT, {"text": "一半"}))
    await projector.on_event(
        _ev(run_events.RUN_FAILED, {"code": 11091, "reason": "chat_unknown", "detail": "boom", "reference_id": "ref-1"})
    )

    extra = json.loads(store.rows[0].extra)
    assert extra == {
        "error": True,
        "error_msg": "boom",
        "error_code": 11091,
        "error_type": "chat_unknown",
        "detail": "boom",
        "reference_id": "ref-1",
        "run_id": RUN_ID,
    }
    assert json.loads(store.rows[0].message)["msg"] == "一半"


async def test_direct_teardown_without_terminal_event_saves_what_exists(store):
    projector = _direct()
    await projector.on_event(_ev(run_events.RUN_STARTED))
    await projector.on_event(_ev(run_events.TEXT, {"text": "流到一半"}))
    await projector.aclose()
    await projector.aclose()

    assert len(store.rows) == 1
    assert json.loads(store.rows[0].message)["msg"] == "流到一半"
    assert json.loads(store.rows[0].extra) == {"error": True, "error_msg": "stream interrupted", "run_id": RUN_ID}


async def test_direct_skips_subagent_events_and_ignores_other_types(store):
    projector = _direct()
    await projector.on_event(_ev(run_events.THINKING, {"text": "子代理", "call_id": "t", "namespace": "sub:1"}))
    await projector.on_event(
        _ev(
            run_events.TOOL_CALL,
            {"call_id": "n1", "name": "grep", "status": "start", "extra_info": {"namespace": "sub:1"}},
        )
    )
    await projector.on_event(_ev(run_events.PLAN, {"items": []}))
    await projector.on_event(_ev(run_events.TEXT, {"text": "答"}))
    await projector.on_event(_ev(run_events.RUN_FINISHED))

    assert json.loads(store.rows[0].message) == {"msg": "答", "events": [{"type": "text", "content": "答"}]}


# ----------------------------------------------------------------- planned


class _TaskStore:
    """In-memory linsight_execute_task. Whole-row reads are forbidden (K4)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.inserts = 0
        self.updates = 0

    async def get_plan_columns_by_session_version_id(self, session_version_id: str):
        return [
            (row["id"], row["status"], row["task_data"])
            for row in self.rows.values()
            if row["session_version_id"] == session_version_id
        ]

    async def batch_create_tasks(self, tasks: list[LinsightExecuteTask]):
        self.inserts += 1
        for task in tasks:
            assert task.id not in self.rows, "duplicate primary key"
            self.rows[task.id] = task.model_dump()
        return tasks

    async def update_fields_by_id(self, task_id: str, **kwargs) -> None:
        self.updates += 1
        assert task_id in self.rows
        assert "history" not in kwargs
        self.rows[task_id].update(kwargs)

    async def update_by_id(self, *args, **kwargs):
        raise AssertionError("update_by_id reads the whole row back")

    async def get_by_session_version_id(self, *args, **kwargs):
        raise AssertionError("whole rows must not be read")

    async def get_by_id(self, *args, **kwargs):
        raise AssertionError("whole rows must not be read")

    @property
    def writes(self) -> int:
        return self.inserts + self.updates


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _PlanSource:
    """Plan events exactly as a run produces them: mapper diff -> unified output."""

    def __init__(self) -> None:
        self.mapper = StreamEventMapper(SVID)
        self.events: list[dict] = []

        async def sink(event: dict) -> None:
            self.events.append(event)

        self.output = UnifiedEventOutput(self.mapper, sink, run_id=RUN_ID)

    def write_todos(self, todos: list[dict]) -> dict:
        (event,) = self.output.convert(self.mapper._diff_todos(todos))
        assert event["type"] == run_events.PLAN
        self.events.append(event)
        return event


TODOS_V1 = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
    {"content": "3. 做海报", "status": "pending"},
]
# Row 1 done, row 2 reworded in place, row 3 dropped by the model.
TODOS_V2 = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 做 PPT", "status": "in_progress"},
]


@pytest.fixture
def tasks():
    return _TaskStore()


def _planned(tasks: _TaskStore, clock: _Clock | None = None, **overrides) -> PlannedRunProjector:
    return PlannedRunProjector(SVID, run_id=RUN_ID, dao=tasks, clock=clock or _Clock(), **overrides)


async def test_planned_previous_name_persisted(tasks):
    source = _PlanSource()
    clock = _Clock()
    projector = _planned(tasks, clock)

    await projector.on_event(source.write_todos(TODOS_V1))
    assert [row["task_data"]["name"] for row in tasks.rows.values()] == ["1. 收集资料", "2. 写报告", "3. 做海报"]
    assert all("previous_name" not in row["task_data"] for row in tasks.rows.values())
    assert all(row["session_version_id"] == SVID for row in tasks.rows.values())

    clock.now += 10
    v2 = source.write_todos(TODOS_V2)
    await projector.on_event(v2)

    reworded_id = v2["data"]["items"][1]["id"]
    row = tasks.rows[reworded_id]
    assert row["task_data"]["name"] == "2. 做 PPT"
    assert row["task_data"]["previous_name"] == "2. 写报告"
    assert row["status"] == ExecuteTaskStatusEnum.IN_PROGRESS
    # The row kept its id: reworded, not replaced.
    assert len(tasks.rows) == 3
    done = tasks.rows[v2["data"]["items"][0]["id"]]
    assert done["status"] == ExecuteTaskStatusEnum.SUCCESS


async def test_planned_cancelled_persisted(tasks):
    source = _PlanSource()
    clock = _Clock()
    projector = _planned(tasks, clock)

    await projector.on_event(source.write_todos(TODOS_V1))
    clock.now += 10
    v2 = source.write_todos(TODOS_V2)
    await projector.on_event(v2)

    (cancelled,) = [item for item in v2["data"]["items"] if item["status"] == run_events.PLAN_CANCELLED]
    row = tasks.rows[cancelled["id"]]
    assert row["status"] == ExecuteTaskStatusEnum.TERMINATED
    # The row stays, with its wording, so the panel can show it as cancelled.
    assert row["task_data"]["name"] == "3. 做海报"


async def test_planned_write_throttled(tasks):
    source = _PlanSource()
    clock = _Clock()
    projector = _planned(tasks, clock, min_interval=60.0)

    await projector.on_event(source.write_todos([{"content": f"步骤 {i}", "status": "pending"} for i in range(5)]))
    first_writes = tasks.writes
    assert first_writes == 1  # one batch insert

    # 100 plan events inside one throttle window: the clock does not move.
    for round_no in range(100):
        todos = [
            {"content": f"步骤 {i}", "status": "completed" if (i + round_no) % 2 else "in_progress"} for i in range(5)
        ]
        await projector.on_event(source.write_todos(todos))
    assert tasks.writes == first_writes
    assert projector.flush_count == 1

    await projector.on_event(_ev(run_events.RUN_FINISHED))
    await projector.aclose()

    # One more flush, and it writes each changed row once.
    assert projector.flush_count == 2
    assert tasks.writes <= first_writes + 5
    assert await load_plan(SVID, dao=tasks) == source.events[-1]["data"]["items"]


async def test_planned_trailing_flush_without_further_events(tasks):
    source = _PlanSource()
    projector = PlannedRunProjector(SVID, dao=tasks, min_interval=0.02)

    await projector.on_event(source.write_todos(TODOS_V1))
    await projector.on_event(source.write_todos(TODOS_V2))
    assert projector.flush_count == 1

    await asyncio.sleep(0.1)
    assert projector.flush_count == 2
    assert await load_plan(SVID, dao=tasks) == source.events[-1]["data"]["items"]
    await projector.aclose()


async def test_plan_reload_matches_stream(tasks):
    source = _PlanSource()
    clock = _Clock()
    projector = _planned(tasks, clock)

    for todos in (
        TODOS_V1,
        TODOS_V2,
        # A row inserted in the middle, and a new one at the end.
        [
            {"content": "1. 收集资料", "status": "completed"},
            {"content": "1.5 核对数据", "status": "in_progress"},
            {"content": "2. 做 PPT", "status": "pending"},
            {"content": "4. 发邮件", "status": "pending"},
        ],
    ):
        clock.now += 10
        await projector.on_event(source.write_todos(todos))
    await projector.aclose()

    last_plan = source.events[-1]["data"]["items"]
    assert {item["status"] for item in last_plan} >= {run_events.PLAN_CANCELLED, run_events.PLAN_COMPLETED}
    assert any(item.get("previous_content") for item in last_plan)
    assert await load_plan(SVID, dao=tasks) == last_plan

    # A projector started in another process (resume, relay) continues from the
    # rows instead of inserting them again.
    resumed = _planned(tasks, _Clock())
    await resumed.on_event(source.events[-1])
    await resumed.aclose()
    assert await load_plan(SVID, dao=tasks) == last_plan


async def test_planned_default_dao_is_the_execute_task_dao():
    assert PlannedRunProjector(SVID)._dao is planned_module.LinsightExecuteTaskDao


async def test_stopped_row_is_not_an_error_row_and_keeps_its_content(store):
    """Design §7 item 2: a user stop has its own mark; a failure and a torn-down run keep theirs."""
    stopped, failed, torn = _direct(), _direct(), _direct()
    for projector in (stopped, failed, torn):
        await projector.on_event(_ev(run_events.TEXT, {"text": "已经写出的部分"}))
    await stopped.on_event(_ev(run_events.RUN_STOPPED, run_events.stopped_data()))
    await failed.on_event(
        _ev(run_events.RUN_FAILED, {"code": 11091, "reason": "chat_unknown", "detail": "boom", "reference_id": "r"})
    )
    await torn.aclose()

    stopped_extra, failed_extra, torn_extra = (json.loads(row.extra) for row in store.rows)
    assert stopped_extra == {"status": "stopped", "run_id": RUN_ID}
    assert failed_extra["error"] is True and "status" not in failed_extra
    # No terminal event at all is still an interrupted turn, as before.
    assert torn_extra == {"error": True, "error_msg": "stream interrupted", "run_id": RUN_ID}
    assert [json.loads(row.message)["msg"] for row in store.rows] == ["已经写出的部分"] * 3


def test_run_stopped_data_shape():
    assert run_events.stopped_data() == {"reason": "user", "status": "stopped", "unread_messages": []}
    assert run_events.stopped_data([{"message_id": "m-1", "text": "补充", "files": [{"file_id": "f"}], "ts": 1}]) == {
        "reason": "user",
        "status": "stopped",
        "unread_messages": [{"message_id": "m-1", "text": "补充", "files": [{"file_id": "f"}]}],
    }

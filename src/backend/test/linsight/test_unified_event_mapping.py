"""Unified run events produced by the stream event mapper (F004 T017/T018).

The mapper keeps its ``BaseEvent`` output for the legacy WebSocket path and gains
a second, opt-in output: ``UnifiedEventOutput`` turns the same stream into the
event types of design §4.3 and hands them to an injected sink (in production
``EventWriter.emit`` / ``RunEventStream.append``; here a list).

Every test drives the REAL ``planned`` graph built by ``create_linsight_agent``
with a scripted model. No Redis, no database, no LLM.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from bisheng.linsight.domain.schemas.run_events import PlanData, RunFailedData, plan_progress
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper, UnifiedEventOutput
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng_langchain.linsight.event import BaseEvent, GenerateSubTask, TaskEnd

SVID = "sv-unified"
RUN_ID = "run-1"

TODOS_V1 = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
    {"content": "3. 做海报", "status": "pending"},
]
# Row 1 done, row 2 reworded (same position), row 3 dropped by the model.
TODOS_V2 = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 做 PPT", "status": "in_progress"},
]
TODOS_V3 = [
    {"content": "1. 收集资料", "status": "completed"},
    {"content": "2. 做 PPT", "status": "completed"},
]


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _UnifiedScriptedModel(BaseChatModel):
    """Replays a fixed list of replies; an Exception entry is raised instead."""

    script: list[Any]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-unified-events"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17): create_linsight_agent
        # registers a process-wide harness profile per provider name.
        return {"ls_provider": "f004-unified-event-mapping", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _UnifiedScriptedModel:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        reply = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(reply, BaseException):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _MemoryObjectStore:
    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str, object_name: str, file: bytes, **_: Any) -> None:
        self.objects[object_name] = file

    def put_object_sync(self, bucket_name: str, object_name: str, file: bytes, **_: Any) -> None:
        self.objects[object_name] = file

    async def get_object(self, bucket_name: str, object_name: str) -> bytes:
        return self.objects[object_name]

    def get_object_sync(self, bucket_name: str, object_name: str) -> bytes:
        return self.objects[object_name]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]


async def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path, script: list[Any]
) -> tuple[list[dict[str, Any]], list[BaseEvent]]:
    """Run the planned graph and drive it the way a run driver would.

    Returns the unified events the sink received and the legacy ``BaseEvent``
    list the same mapper produced.
    """
    from bisheng.core.config.settings import LinsightConf

    model = _UnifiedScriptedModel(script=script)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
    session = SimpleNamespace(id=SVID, session_id="chat-unified", tenant_id=1, user_id=1, question="q", api_meta=None)
    backend = WorkspaceBackend(svid=SVID, minio=_MemoryObjectStore(), file_dir=str(tmp_path))
    agent = await agent_factory.create_linsight_agent(session, [], backend=backend, file_dir=str(tmp_path))

    unified: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        unified.append(event)

    output = UnifiedEventOutput(StreamEventMapper(svid=SVID), sink, run_id=RUN_ID)
    legacy: list[BaseEvent] = []
    await output.run_started()
    interrupted = False
    try:
        async for namespace, mode, chunk in agent.astream(
            {"messages": [("user", "写一份报告")]},
            config={"configurable": {"thread_id": "t-unified"}, "recursion_limit": 40},
            stream_mode=["updates", "messages", "values"],
            subgraphs=True,
        ):
            legacy.extend(await output.feed(mode, chunk, namespace or None))
            if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
                interrupted = True
    except Exception as exc:
        await output.run_failed(exc)
    else:
        if not interrupted:
            await output.run_finished()
    return unified, legacy


def _types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def _plans(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [e["data"]["items"] for e in events if e["type"] == "plan"]


PLANNED_SCRIPT = [
    _call("write_todos", {"todos": TODOS_V1}, "c1"),
    _call("write_todos", {"todos": TODOS_V2}, "c2"),
    _call("write_todos", {"todos": TODOS_V3}, "c3"),
    AIMessage(content="报告写好了。"),
]


async def test_planned_event_sequence(monkeypatch: pytest.MonkeyPatch, tmp_path):
    events, legacy = await _run(monkeypatch, tmp_path, PLANNED_SCRIPT)
    types = _types(events)

    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert types.count("run_finished") == 1
    for expected in ("plan", "tool_call", "text"):
        assert expected in types
    # The plan arrives before the answer, and the answer before the run ends.
    assert types.index("plan") < types.index("text") < types.index("run_finished")
    assert all(e["run_id"] == RUN_ID for e in events)

    tool_calls = [e["data"] for e in events if e["type"] == "tool_call"]
    todo_calls = [d for d in tool_calls if d["name"] == "write_todos"]
    assert [d["status"] for d in todo_calls] == ["start", "end"] * 3
    # Start and end of one call share a call id; different calls do not.
    assert todo_calls[0]["call_id"] == todo_calls[1]["call_id"] != todo_calls[2]["call_id"]
    assert todo_calls[1]["output"]

    assert "".join(e["data"]["text"] for e in events if e["type"] == "text") == "报告写好了。"

    # The legacy output is still produced by the same mapper, untouched.
    assert any(isinstance(e, GenerateSubTask) for e in legacy)
    assert any(isinstance(e, TaskEnd) and e.status == "terminated" for e in legacy)


async def test_plan_event_full_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path):
    events, _legacy = await _run(monkeypatch, tmp_path, PLANNED_SCRIPT)
    plans = _plans(events)
    assert len(plans) == 3
    for items in plans:
        PlanData(items=items)  # every snapshot satisfies the schema
        assert all({"id", "content", "status"} <= set(item) for item in items)

    first, second, third = plans
    assert [(i["content"], i["status"]) for i in first] == [
        ("1. 收集资料", "in_progress"),
        ("2. 写报告", "pending"),
        ("3. 做海报", "pending"),
    ]
    assert not any("previous_content" in i for i in first)

    # Every later snapshot is the whole plan again, with the same row ids.
    assert [i["id"] for i in second] == [i["id"] for i in first]
    assert [i["id"] for i in third] == [i["id"] for i in first]
    reworded = second[1]
    assert reworded["content"] == "2. 做 PPT"
    assert reworded["previous_content"] == "2. 写报告"
    assert reworded["status"] == "in_progress"
    # The old wording stays on the row in later snapshots (AC-10), although the
    # third update only flipped a status.
    assert third[1]["previous_content"] == "2. 写报告"
    assert third[1]["status"] == "completed"
    assert "previous_content" not in third[0]


async def test_plan_progress_counts(monkeypatch: pytest.MonkeyPatch, tmp_path):
    events, _legacy = await _run(monkeypatch, tmp_path, PLANNED_SCRIPT)
    plans = _plans(events)
    # completed / total; the cancelled row leaves the total.
    assert [plan_progress(items) for items in plans] == [(0, 3), (1, 2), (2, 2)]


async def test_cancelled_item_status(monkeypatch: pytest.MonkeyPatch, tmp_path):
    events, _legacy = await _run(monkeypatch, tmp_path, PLANNED_SCRIPT)
    first, second, third = _plans(events)
    dropped_id = first[2]["id"]

    for items in (second, third):
        dropped = [i for i in items if i["id"] == dropped_id]
        assert dropped == [{"id": dropped_id, "content": "3. 做海报", "status": "cancelled"}]
        assert [i["status"] for i in items].count("cancelled") == 1
    # The cancelled row keeps its place in the list.
    assert [i["id"] for i in second].index(dropped_id) == 2


async def test_run_failed_fields(monkeypatch: pytest.MonkeyPatch, tmp_path):
    events, _legacy = await _run(
        monkeypatch,
        tmp_path,
        [_call("write_todos", {"todos": TODOS_V1}, "c1"), ValueError("upstream exploded at http://10.0.0.8:9000/v1")],
    )
    types = _types(events)
    assert types[0] == "run_started"
    assert types[-1] == "run_failed"
    assert "run_finished" not in types
    # Everything produced before the failure is still there (AC-32).
    assert "plan" in types

    data = events[-1]["data"]
    assert {"code", "reason", "detail", "reference_id"} <= set(data)
    RunFailedData(**data)
    assert isinstance(data["code"], int) and 10000 <= data["code"] <= 99999
    assert data["reason"]
    assert "ValueError" in data["detail"]
    # The detail is the redacted public text, not the raw exception string.
    assert "10.0.0.8" not in data["detail"]
    assert data["reference_id"]


async def test_interrupt_maps_to_ask_user(monkeypatch: pytest.MonkeyPatch, tmp_path):
    question = {"question": "面向哪个行业？", "options": ["金融", "制造"], "multiple": False}
    events, _legacy = await _run(
        monkeypatch,
        tmp_path,
        [_call("ask_user", {"reason": "开始前请确认", "questions": [question]}, "c1"), AIMessage(content="done")],
    )
    types = _types(events)
    assert types.count("ask_user") == 1
    # The run is waiting for the answer: it has not ended.
    assert not {"run_finished", "run_failed", "run_stopped"} & set(types)

    data = next(e["data"] for e in events if e["type"] == "ask_user")
    assert data["reason"] == "开始前请确认"
    assert [(q["question"], q["options"]) for q in data["questions"]] == [("面向哪个行业？", ["金融", "制造"])]
    # The card refers to the ask_user tool call that is still open.
    open_call = next(e["data"] for e in events if e["type"] == "tool_call" and e["data"]["name"] == "ask_user")
    assert data["call_id"] == open_call["call_id"]


async def test_terminal_event_is_emitted_once():
    """After a terminal event nothing else reaches the sink."""
    received: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        received.append(event)

    output = UnifiedEventOutput(StreamEventMapper(svid=SVID), sink)
    await output.run_started()
    await output.run_stopped("user")
    await output.run_finished()
    await output.feed("messages", (AIMessage(content="late"), {}), None)
    assert _types(received) == ["run_started", "run_stopped"]
    assert "run_id" not in received[0]

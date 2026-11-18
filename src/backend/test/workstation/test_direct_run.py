"""F004 T027: the executor of a ``direct`` run (design 决策 3, 7, 9, 10).

Covers AC-21 (the answer continues the parked run), AC-22 (a parked run holds no
lease), AC-29 (stop within 5 s, output kept), AC-34 (nothing local is created
before the model request) and AC-37 (one quota admission per run).

The REAL graph from ``create_linsight_agent(profile="direct")`` runs with a
scripted model. Redis is fakeredis, the object store is a dict, the clock and
the watcher's sleep are fakes.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper, UnifiedEventOutput
from bisheng.linsight.domain.services.tool_assembly import ToolAssembly
from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "conv-direct-1"
TENANT = 3
USER = 7
SUMMARY_TEXT = "SUMMARY-OF-EARLIER-STEPS"


def _call(name: str, args: dict[str, Any], call_id: str, content: str = "") -> AIMessage:
    return AIMessage(content=content, tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _DirectRunModel(BaseChatModel):
    """Replays a script. An item is a message, an exception, or an async callable
    ``(messages) -> message`` (to block, to set the stop flag, to inspect state).
    A request without a system message is a summarisation request."""

    script: list[Any]
    calls: int = 0
    summary_calls: int = 0
    inputs: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17).
        return {"ls_provider": "f004-direct-run", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _DirectRunModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        raise AssertionError("the direct run must call the model asynchronously")

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> Any:
        if not any(isinstance(m, SystemMessage) for m in messages):
            self.summary_calls += 1
            return ChatResult(generations=[ChatGeneration(message=AIMessage(SUMMARY_TEXT))])
        self.inputs.append(list(messages))
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if callable(item):
            item = await item(messages)
        if isinstance(item, BaseException):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])


class _MemoryObjectStore:
    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    def put_object_sync(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    async def get_object(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def get_object_sync(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    async def copy_object(
        self, source_bucket: str = None, source_object: str = None, dest_bucket: str = None, dest_object: str = None
    ) -> None:
        self.objects[dest_object] = self.objects[source_object]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@tool
def echo(text: str) -> str:
    """Repeat the text."""
    return f"echo:{text}"


@tool
def fetch(page: int) -> str:
    """Fetch one page of a long document."""
    return f"第{page}页 " + "长文档内容" * 500


class _Env:
    """One conversation with its fakes. ``submit`` goes through the real send entry."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path, script: list[Any], tools: list | None = None):
        from bisheng.core.config.settings import LinsightConf

        self.model = _DirectRunModel(script=script)
        monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(self.model, False)))
        monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
        monkeypatch.setattr(direct_run, "_HOOK_FACTORIES", [])
        self.clock = FakeClock()
        self.redis = fakeredis.aioredis.FakeRedis()
        self.relays: list[dict] = []
        self.lease = RunLeaseService(self.redis, clock=self.clock)
        self.dispatch = RunDispatchService(self.redis, clock=self.clock, enqueue_relay=self._enqueue)
        self.stream = RunEventStream(self.redis, wall_clock=self.clock)
        self.store = _MemoryObjectStore()
        self.file_dir = str(tmp_path / "cache" / CID)
        self.admissions: list[str] = []
        self.admit_error: BaseException | None = None
        self.finished: list[tuple[str, str]] = []
        self.hook_events: list[dict] = []
        self.tools = list(tools or [])
        real_finish = self.dispatch.on_run_finished

        async def on_run_finished(conversation_id: str, run_id: str | None = None):
            self.finished.append((conversation_id, run_id))
            return await real_finish(conversation_id, run_id)

        self.dispatch.on_run_finished = on_run_finished
        self.runner = self.make_runner()

    def make_runner(self, **overrides: Any) -> DirectRunner:
        kwargs: dict[str, Any] = {
            "redis": self.redis,
            "clock": self.clock,
            "sleep": self._sleep,
            "stream": self.stream,
            "lease": self.lease,
            "dispatch": self.dispatch,
            "checkpointer": getattr(self, "checkpointer", None) or InMemorySaver(),
            "admit": self._admit,
            "assemble": self._assemble,
            "build_input": self._build_input,
            "object_store": self._object_store,
            "file_dir_for": lambda ctx: self.file_dir,
            "recursion_limit": 60,
        }
        self.checkpointer = kwargs["checkpointer"]
        kwargs.update(overrides)
        return DirectRunner(**kwargs)

    async def _enqueue(self, item: dict) -> None:
        self.relays.append(item)

    async def _sleep(self, seconds: float) -> None:
        # One watcher tick: the fake clock moves by the requested time.
        self.clock.now += seconds
        await asyncio.sleep(0.002)

    async def _admit(self, ctx: DirectRunContext) -> None:
        self.admissions.append(ctx.run_id)
        if self.admit_error is not None:
            raise self.admit_error

    async def _assemble(self, ctx: DirectRunContext, file_dir: str) -> ToolAssembly:
        return ToolAssembly(tools=list(self.tools))

    @staticmethod
    async def _build_input(ctx: DirectRunContext) -> dict:
        return {"messages": [{"role": "user", "content": ctx.text}]}

    async def _object_store(self) -> _MemoryObjectStore:
        return self.store

    def hook(self, event: dict) -> None:
        self.hook_events.append(event)

    def message(self, text: str) -> dict:
        return {"text": text, "task_mode": False, "user_id": USER, "tenant_id": TENANT}

    async def submit(self, text: str) -> DirectRunContext:
        result = await self.dispatch.submit(CID, self.message(text))
        assert result.disposition == "started"
        return DirectRunContext(
            conversation_id=CID,
            run_id=result.run_id,
            tenant_id=TENANT,
            user_id=USER,
            message_id=result.message_id,
            text="" if result.kind == "answer" else text,
            is_resume=result.kind == "answer",
            answer=text if result.kind == "answer" else None,
        )

    async def run(self, ctx: DirectRunContext | dict, runner: DirectRunner | None = None):
        return await asyncio.wait_for(
            direct_run.execute_direct_run(ctx, runner=runner or self.runner, on_event=[self.hook]), timeout=20
        )

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CID)]

    async def types(self) -> list[str]:
        return [event["type"] for event in await self.events()]

    async def state(self) -> rl.RunState:
        return await self.lease.get_state(CID)


@pytest.fixture
def make_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _make(script: list[Any], tools: list | None = None) -> _Env:
        return _Env(monkeypatch, tmp_path, script, tools)

    return _make


ASK = _call(
    "ask_user",
    {"reason": "需要确认", "questions": [{"question": "喜欢什么颜色", "options": ["红色", "蓝色"], "multiple": False}]},
    "ask-1",
)


async def test_run_writes_events(make_env):
    env = make_env([_call("echo", {"text": "hi"}, "c1"), AIMessage(content="你好，我是助手")], tools=[echo])
    ctx = await env.submit("你好")

    task = direct_run.start_direct_run(ctx, runner=env.runner, on_event=[env.hook])
    # The module keeps a reference so the coroutine is not garbage collected.
    assert task in direct_run._TASKS
    outcome = await asyncio.wait_for(task, timeout=20)

    assert outcome.status == "finished"
    assert task not in direct_run._TASKS
    events = await env.events()
    assert events[0]["type"] == "run_started"
    assert events[0]["data"]["profile"] == "direct"
    assert events[-1]["type"] == "run_finished"
    assert {event["run_id"] for event in events} == {ctx.run_id}
    tool_frames = [e["data"] for e in events if e["type"] == "tool_call" and e["data"]["name"] == "echo"]
    assert [frame["status"] for frame in tool_frames] == ["start", "end"]
    assert "".join(e["data"]["text"] for e in events if e["type"] == "text") == "你好，我是助手"
    assert (await env.stream.snapshot(CID))["text"] == "你好，我是助手"
    # The model saw the tool result: the graph really ran.
    assert any(isinstance(m, ToolMessage) and m.content == "echo:hi" for m in env.model.inputs[-1])
    # The projector hook receives every event, the terminal one included.
    assert [e["type"] for e in env.hook_events][0] == "run_started"
    assert [e["type"] for e in env.hook_events][-1] == "run_finished"
    assert all(e["run_id"] == ctx.run_id for e in env.hook_events)
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_heartbeat_renews(make_env):
    seen: dict[str, Any] = {}

    async def slow_reply(messages):
        start = env.clock.now
        while env.clock.now < start + 3 * rl.LEASE_SECONDS:
            await asyncio.sleep(0.001)
        seen["valid"] = await env.lease.is_lease_valid(CID)
        seen["state"] = await env.state()
        return AIMessage(content="done")

    env = make_env([slow_reply])
    ctx = await env.submit("慢一点")
    granted_until = (await env.state()).lease_until_ms

    outcome = await env.run(ctx)

    assert outcome.status == "finished"
    # 90 s passed on the clock, three times the lease: only renewals kept it.
    assert seen["valid"] is True
    assert seen["state"].run_id == ctx.run_id
    assert seen["state"].lease_until_ms > granted_until + 2 * rl.LEASE_SECONDS * 1000


async def test_stop_within_5s_keeps_output(make_env):
    seen: dict[str, float] = {}

    async def stopped_mid_answer(messages):
        await env.lease.request_stop(ctx.run_id, CID)
        seen["stop_at"] = env.clock.now
        await asyncio.sleep(30)
        raise AssertionError("the stopped run was not cancelled")

    env = make_env([_call("echo", {"text": "x"}, "c1", content="已经写出的部分回答"), stopped_mid_answer], tools=[echo])
    ctx = await env.submit("写一篇长文")

    outcome = await env.run(ctx)

    assert outcome.status == "stopped"
    assert env.clock.now - seen["stop_at"] <= 5
    events = await env.events()
    assert events[-1]["type"] == "run_stopped"
    assert "run_finished" not in [e["type"] for e in events]
    # Text written before the stop stays in the accumulated state (AC-29).
    assert (await env.stream.snapshot(CID))["text"] == "已经写出的部分回答"
    assert env.finished == [(CID, ctx.run_id)]
    assert (await env.state()).status == rl.STATUS_IDLE
    assert env.hook_events[-1]["type"] == "run_stopped"


async def test_interrupt_parks(make_env):
    env = make_env([ASK, AIMessage(content="不应该走到这里")])
    ctx = await env.submit("帮我选颜色")

    outcome = await env.run(ctx)

    assert outcome.status == "waiting"
    assert env.model.calls == 1
    events = await env.events()
    ask = [e for e in events if e["type"] == "ask_user"]
    assert len(ask) == 1
    assert ask[0]["data"]["reason"] == "需要确认"
    assert ask[0]["data"]["questions"][0]["question"] == "喜欢什么颜色"
    assert ask[0]["data"]["questions"][0]["options"] == ["红色", "蓝色"]
    assert not {"run_finished", "run_failed", "run_stopped"} & {e["type"] for e in events}
    # Parked: the run keeps the conversation but holds no lease (AC-22).
    state = await env.state()
    assert state.status == rl.STATUS_WAITING
    assert state.run_id == ctx.run_id
    assert state.lease_until_ms == 0
    assert await env.lease.is_lease_valid(CID) is False
    assert (await env.stream.snapshot(CID))["pending_question"]["call_id"] == ask[0]["data"]["call_id"]
    # A parked run is not finished.
    assert env.finished == []


async def test_resume_continues(make_env, monkeypatch: pytest.MonkeyPatch):
    env = make_env([ASK, AIMessage(content="好的，用蓝色")])
    first = await env.submit("帮我选颜色")
    assert (await env.run(first)).status == "waiting"
    seeded: list[Any] = []
    real_seed = UnifiedEventOutput.seed_plan
    monkeypatch.setattr(
        UnifiedEventOutput, "seed_plan", lambda self, items: (seeded.append(items), real_seed(self, items))[1]
    )
    plan = [{"id": "row-a", "content": "第一步", "status": "completed"}]
    await env.stream.update_snapshot(CID, plan=plan)

    # The answer goes through the same send entry and names the parked run.
    second = await env.submit("蓝色")
    assert second.is_resume and second.run_id == first.run_id
    # A fresh runner, as on another node: only Redis and the checkpoint are shared.
    outcome = await env.run(second, runner=env.make_runner())

    assert outcome.status == "finished"
    assert env.model.calls == 2
    # The model continues from the question: the tool call got the answer.
    answers = [m for m in env.model.inputs[-1] if isinstance(m, ToolMessage)]
    assert [m.content for m in answers] == ["蓝色"]
    types = await env.types()
    # Same run: the stream was not restarted.
    assert types.count("run_started") == 1
    assert types.index("ask_user") < types.index("ask_user_answered") < types.index("run_finished")
    events = await env.events()
    answered = next(e for e in events if e["type"] == "ask_user_answered")
    asked = next(e for e in events if e["type"] == "ask_user")
    assert answered["data"] == {"call_id": asked["data"]["call_id"], "answer": "蓝色"}
    snapshot = await env.stream.snapshot(CID)
    assert snapshot["text"] == "好的，用蓝色"
    assert "pending_question" not in snapshot
    # The new mapper took over the plan of the parked run.
    assert seeded == [plan]
    assert env.finished == [(CID, first.run_id)]
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_seed_plan_keeps_ids_and_cancelled_rows():
    emitted: list[dict] = []

    async def sink(event: dict) -> None:
        emitted.append(event)

    output = UnifiedEventOutput(StreamEventMapper(svid="run-x"), sink, run_id="run-x")
    output.seed_plan(
        [
            {"id": "a", "content": "收集资料", "status": "completed"},
            {"id": "b", "content": "旧的一步", "status": "cancelled"},
            {"id": "c", "content": "写报告", "previous_content": "写初稿", "status": "pending"},
        ]
    )

    await output.feed(
        "updates",
        {
            "model": {
                "todos": [
                    {"content": "收集资料", "status": "completed"},
                    {"content": "写报告", "status": "in_progress"},
                ]
            }
        },
    )

    assert [event["type"] for event in emitted] == ["plan"]
    assert emitted[0]["data"]["items"] == [
        {"id": "a", "content": "收集资料", "status": "completed"},
        {"id": "b", "content": "旧的一步", "status": "cancelled"},
        {"id": "c", "content": "写报告", "previous_content": "写初稿", "status": "in_progress"},
    ]


async def test_single_admission_per_run(make_env):
    env = make_env(
        [_call("echo", {"text": "1"}, "c1"), _call("echo", {"text": "2"}, "c2"), AIMessage(content="完成")],
        tools=[echo],
    )
    ctx = await env.submit("连续调用两次工具")

    assert (await env.run(ctx)).status == "finished"

    assert env.model.calls == 3
    assert env.admissions == [ctx.run_id]


async def test_admission_rejection_fails_before_the_model(make_env):
    from bisheng.common.errcode.dsh import DshMonthlyTokenLimitExceededError

    env = make_env([AIMessage(content="不应该被调用")])
    env.admit_error = DshMonthlyTokenLimitExceededError()
    ctx = await env.submit("你好")

    outcome = await env.run(ctx)

    assert outcome.status == "failed"
    assert env.model.calls == 0
    events = await env.events()
    assert [e["type"] for e in events] == ["run_started", "run_failed"]
    assert events[-1]["data"]["code"] == DshMonthlyTokenLimitExceededError.Code
    assert env.finished == [(CID, ctx.run_id)]
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_no_workspace_dir_before_model_call(make_env):
    seen: dict[str, bool] = {}

    async def first_reply(messages):
        seen["dir_at_first_model_call"] = os.path.exists(env.file_dir)
        return _call("write_file", {"file_path": "/output/note.md", "content": "内容"}, "w1")

    async def second_reply(messages):
        seen["dir_after_file_operation"] = os.path.exists(env.file_dir)
        return AIMessage(content="写好了")

    env = make_env([first_reply, second_reply])
    ctx = await env.submit("写一个文件")
    assert not os.path.exists(env.file_dir)

    assert (await env.run(ctx)).status == "finished"

    assert seen["dir_at_first_model_call"] is False
    # The workspace of the conversation appears with the first file operation.
    assert f"workspace/{CID}/output/note.md" in env.store.objects
    assert seen["dir_after_file_operation"] is True
    # T053: the local cache is removed when the run ends; object storage keeps the file.
    assert not os.path.exists(env.file_dir)


async def test_no_workspace_dir_without_file_operation(make_env):
    env = make_env([AIMessage(content="你好")])

    assert (await env.run(await env.submit("你好"))).status == "finished"

    assert not os.path.exists(env.file_dir)
    assert env.store.objects == {}


async def test_finish_triggers_dispatch(make_env):
    async def reply_while_user_interjects(messages):
        queued = await env.dispatch.submit(CID, env.message("再补充一点"))
        assert queued.disposition == "queued"
        return AIMessage(content="第一条的回答")

    env = make_env([reply_while_user_interjects, AIMessage(content="补充的回答")])
    ctx = await env.submit("第一条")

    assert (await env.run(ctx)).status == "finished"

    # The finish rule saw the unread message and handed a relay run to the worker queue.
    assert env.finished == [(CID, ctx.run_id)]
    assert len(env.relays) == 1
    relay = env.relays[0]
    assert relay["relay"] is True and relay["profile"] == "direct" and relay["tenant_id"] == TENANT
    state = await env.state()
    assert state.status == rl.STATUS_RUNNING and state.run_id == relay["run_id"]


async def test_failure_emits_run_failed_and_releases(make_env):
    env = make_env([RuntimeError("provider exploded")])
    ctx = await env.submit("你好")

    outcome = await env.run(ctx)

    assert outcome.status == "failed"
    assert isinstance(outcome.error, RuntimeError)
    events = await env.events()
    assert events[-1]["type"] == "run_failed"
    assert {"code", "reason", "detail", "reference_id"} <= set(events[-1]["data"])
    assert env.finished == [(CID, ctx.run_id)]
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_worker_entry_runs_relay_item_and_restores_tenant(make_env, monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    async def interjected(messages):
        await env.dispatch.submit(CID, env.message("接力的问题"))
        return AIMessage(content="第一条的回答")

    async def relay_reply(messages):
        seen["tenant"] = get_current_tenant_id()
        return AIMessage(content="接力的回答")

    env = make_env([interjected, relay_reply])
    assert (await env.run(await env.submit("第一条"))).status == "finished"
    item = env.relays[0]
    monkeypatch.setattr(linsight_utils, "build_prior_conversation_summary", AsyncMock(return_value=""))
    before = get_current_tenant_id()

    # The worker passes the plain queue item; the default input reads the inbox.
    worker_runner = env.make_runner(build_input=None)
    outcome = await env.run(dict(item), runner=worker_runner)

    assert outcome.status == "finished"
    assert seen["tenant"] == TENANT
    assert get_current_tenant_id() == before
    last_user_turn = [m for m in env.model.inputs[-1] if m.type == "human"][-1]
    assert "接力的问题" in last_user_turn.content
    # The thread carried the first turn over to the relay run.
    assert any(m.type == "ai" and m.content == "第一条的回答" for m in env.model.inputs[-1])
    assert await env.dispatch.inbox_length(CID) == 0
    events = await env.events()
    assert events[0]["type"] == "run_started" and events[0]["data"]["relay"] is True
    assert {e["run_id"] for e in events} == {item["run_id"]}
    assert (await env.stream.snapshot(CID))["text"] == "接力的回答"
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_run_that_lost_the_conversation_writes_nothing(make_env):
    env = make_env([AIMessage(content="不应该被调用")])
    ctx = await env.submit("你好")
    env.clock.now += rl.LEASE_SECONDS + 1
    newer = await env.dispatch.submit(CID, env.message("新的问题"))
    before = await env.types()

    outcome = await env.run(ctx)

    assert outcome.status == "lease_lost"
    assert env.model.calls == 0
    assert await env.types() == before
    # The newer run still holds the conversation.
    assert (await env.state()).run_id == newer.run_id


async def test_summary_model_output_is_not_answer_text(make_env, monkeypatch: pytest.MonkeyPatch):
    async def small_window(model, svid, sink):
        model.profile = {"max_input_tokens": 30000}
        if sink is not None:
            sink.update(window=30000, kind="known", usable_input=30000, source="test")

    monkeypatch.setattr(agent_factory, "_apply_context_window", small_window)
    script = [_call("fetch", {"page": i}, f"f{i}") for i in range(30)] + [AIMessage(content="最终回答")]
    env = make_env(script, tools=[fetch])

    runner = env.make_runner(recursion_limit=200)
    assert (await env.run(await env.submit("读完这份长文档"), runner=runner)).status == "finished"

    # The run really compressed its context ...
    assert env.model.summary_calls >= 1
    # ... and the summariser's output never reached the user.
    text = "".join(e["data"]["text"] for e in await env.events() if e["type"] == "text")
    assert text == "最终回答"
    assert SUMMARY_TEXT not in (await env.stream.snapshot(CID))["text"]
    assert not any(SUMMARY_TEXT in str(e.get("data")) for e in env.hook_events)


async def test_metric_line_emitted(make_env):
    """T038 (AC-34): one ``BS_METRIC domain=agent_run`` line per execution.

    Fake clock: the run waits 0.5 s between ``submit`` and the start of the
    execution (queue), admission takes 0.2 s more, so the first model request
    goes out 0.7 s after the message was accepted. One steer message is read
    1.5 s after it entered the inbox (recorded the way the inbox middleware will).
    """
    from loguru import logger

    from bisheng.linsight.domain.services import run_metrics

    async def reply_after_steer(messages):
        run_metrics.record_steer_wait(1500.0)
        return AIMessage(content="你好")

    env = make_env([reply_after_steer])
    ctx = await env.submit("你好")
    env.clock.now += 0.5

    async def slow_admit(run_ctx: DirectRunContext) -> None:
        env.clock.now += 0.2

    lines: list[str] = []
    sink_id = logger.add(lambda m: lines.append(str(m).rstrip("\n")), level="INFO", format="{message}")
    try:
        # The watcher's tick does not move the clock here: only the steps above do.
        runner = env.make_runner(admit=slow_admit, sleep=lambda seconds: asyncio.sleep(0.002))
        assert (await env.run(ctx, runner=runner)).status == "finished"
    finally:
        logger.remove(sink_id)

    metric_lines = [line for line in lines if line.startswith("BS_METRIC domain=agent_run ")]
    assert len(metric_lines) == 1
    fields = dict(part.split("=", 1) for part in metric_lines[0].split()[2:])
    assert {"prep_ms", "queue_ms", "steer_wait_ms", "checkpoint_bytes"} <= set(fields)
    assert fields["profile"] == "direct"
    assert fields["status"] == "finished"
    assert float(fields["queue_ms"]) == pytest.approx(500.0)
    assert float(fields["prep_ms"]) == pytest.approx(700.0)
    assert float(fields["steer_wait_ms"]) == pytest.approx(1500.0)
    assert fields["steer_count"] == "1"
    assert int(fields["checkpoint_bytes"]) > 0
    # No ids in the line: the trace id of the log line carries the run id.
    assert ctx.run_id not in metric_lines[0]


async def test_stop_returns_unread_messages_and_starts_no_relay(make_env):
    """Design §7 items 2 and 6: ``run_stopped`` carries the unread inbox; no relay run starts."""
    sent: dict[str, str] = {}

    async def stopped_mid_answer(messages):
        # Sent while this model call is in flight: the inbox middleware never reads it.
        queued = await env.dispatch.submit(CID, env.message("顺便再查一下乙"))
        sent["message_id"] = queued.message_id
        await env.lease.request_stop(ctx.run_id, CID)
        await asyncio.sleep(30)
        raise AssertionError("the stopped run was not cancelled")

    env = make_env([_call("echo", {"text": "x"}, "c1", content="已经写出的部分回答"), stopped_mid_answer], tools=[echo])
    ctx = await env.submit("写一篇长文")

    outcome = await env.run(ctx)

    assert outcome.status == "stopped"
    stopped = (await env.events())[-1]
    assert stopped["type"] == "run_stopped"
    assert stopped["data"] == {
        "reason": "user",
        "status": "stopped",
        "unread_messages": [{"message_id": sent["message_id"], "text": "顺便再查一下乙", "files": []}],
    }
    # The hooks (the answer-row projector) get the same event.
    assert env.hook_events[-1]["data"] == stopped["data"]
    # No relay run was queued and the conversation is idle with an empty inbox.
    assert env.relays == []
    assert await env.dispatch.inbox_length(CID) == 0
    assert (await env.state()).status == rl.STATUS_IDLE
    # What was written before the stop is kept (AC-29).
    assert (await env.stream.snapshot(CID))["text"] == "已经写出的部分回答"


async def test_finished_run_still_relays_its_unread_messages(make_env):
    """Only a user stop takes the messages back; a run that ends normally relays as before."""

    async def answer_after_a_late_message(messages):
        await env.dispatch.submit(CID, env.message("顺便再查一下乙"))
        return AIMessage("回答完毕")

    env = make_env([answer_after_a_late_message])
    ctx = await env.submit("写一篇长文")

    outcome = await env.run(ctx)

    assert outcome.status == "finished"
    assert len(env.relays) == 1 and env.relays[0]["relay"] is True
    assert await env.dispatch.inbox_length(CID) == 1


# ---------------------------------------------- fields added to the terminal event


class _TerminalFields:
    """Owner of a hook that adds fields to the terminal event (the projector's protocol)."""

    def __init__(self, extra: Any = None, error: BaseException | None = None) -> None:
        self.extra = extra
        self.error = error
        self.asked: list[str] = []
        self.seen: list[dict] = []

    async def before_terminal(self, event: dict) -> Any:
        self.asked.append(event["type"])
        if self.error is not None:
            raise self.error
        return self.extra

    async def on_event(self, event: dict) -> None:
        self.seen.append(event)


async def test_terminal_event_carries_the_fields_of_the_hook_owner(make_env):
    env = make_env([AIMessage(content="你好")])
    files = [{"file_id": "copy-1", "workspace_file_id": "live-1", "path": "output/a.md"}]
    owner = _TerminalFields({"answer_files": files, "status": "must not replace an existing field"})
    ctx = await env.submit("你好")

    outcome = await asyncio.wait_for(
        direct_run.execute_direct_run(ctx, runner=env.runner, on_event=[owner.on_event, env.hook]), timeout=20
    )

    assert outcome.status == "finished"
    # Asked once, for the terminal event only, before it reached the stream.
    assert owner.asked == ["run_finished"]
    terminal = (await env.events())[-1]
    assert terminal["type"] == "run_finished"
    assert terminal["data"]["answer_files"] == files
    assert owner.seen[-1]["data"]["answer_files"] == files


async def test_terminal_event_is_written_when_the_hook_owner_fails(make_env):
    env = make_env([AIMessage(content="你好")])
    owner = _TerminalFields(error=RuntimeError("object storage down"))
    ctx = await env.submit("你好")

    outcome = await asyncio.wait_for(
        direct_run.execute_direct_run(ctx, runner=env.runner, on_event=[owner.on_event]), timeout=20
    )

    assert outcome.status == "finished"
    terminal = (await env.events())[-1]
    assert terminal["type"] == "run_finished" and "answer_files" not in terminal["data"]
    assert owner.seen[-1]["type"] == "run_finished"

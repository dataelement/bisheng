"""F004 T040: the inbox middleware (AC-14, AC-15, AC-16, AC-18, AC-19, AC-23).

The REAL graph from ``create_linsight_agent`` runs with a scripted model. Redis
is fakeredis (the Lua of the send entry works on it), and messages enter the
inbox through the real send entry, ``RunDispatchService.submit``, while the
scripted model is "busy" with one of its calls.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from bisheng.linsight.domain.services import agent_factory, run_metrics
from bisheng.linsight.domain.services.inbox_middleware import INBOX_SOURCE, InboxMiddleware
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.tool_assembly import ToolAssembly
from bisheng.linsight.domain.services.unattended_run import OPEN_API_CHANNEL
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services.direct_run import DirectRunContext, DirectRunner
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CID = "chat-inbox"
TENANT = 7
USER = 3
TODOS = [
    {"content": "1. 收集资料", "status": "in_progress"},
    {"content": "2. 写报告", "status": "pending"},
]


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _InboxModel(BaseChatModel):
    """Replays a script. ``on_call(index)`` runs while model call ``index`` is "in flight"."""

    script: list[AIMessage]
    on_call: Any = None
    calls: int = 0
    inputs: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17).
        return {"ls_provider": "f004-inbox-middleware", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _InboxModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        raise AssertionError("the graph must call the model asynchronously")

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> Any:
        if not any(isinstance(m, SystemMessage) for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage("summary"))])
        index = self.calls
        self.calls += 1
        self.inputs.append(list(messages))
        if self.on_call is not None:
            await self.on_call(index)
        return ChatResult(generations=[ChatGeneration(message=self.script[min(index, len(self.script) - 1)])])


class _MemoryObjectStore:
    """The slice of the MinIO client ``WorkspaceBackend`` uses, kept in a dict."""

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


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


SCRIPT = [
    _call("write_todos", {"todos": TODOS}, "c1"),
    _call("ls", {"path": "/"}, "c2"),
    AIMessage(content="done"),
]


class _Env:
    """One conversation: fakeredis, the real send entry, the real factory graph."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path, script: list[AIMessage] | None = None):
        from bisheng.core.config.settings import LinsightConf

        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.model = _InboxModel(script=script or SCRIPT)
        monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(self.model, False)))
        monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))
        self.clock = FakeClock()
        self.redis = fakeredis.aioredis.FakeRedis()
        self.dispatch = RunDispatchService(self.redis, clock=self.clock)
        self.events: list[dict] = []
        self.waits: list[float] = []
        self.checkpointer = InMemorySaver()
        self.run_id = ""

    async def emit(self, event: dict) -> None:
        self.events.append(event)

    def message(self, text: str, **extra: Any) -> dict:
        return {"text": text, "task_mode": False, "user_id": USER, "tenant_id": TENANT, **extra}

    async def start(self, text: str = "写一份报告") -> None:
        """The first message of the conversation starts the run (it never enters the inbox)."""
        result = await self.dispatch.submit(CID, self.message(text))
        assert result.disposition == "started"
        self.run_id = result.run_id

    async def steer(self, text: str) -> str:
        """A message sent while the run holds the conversation; returns its message id."""
        result = await self.dispatch.submit(CID, self.message(text))
        assert result.disposition == "queued"
        return result.message_id

    def middleware(self) -> InboxMiddleware:
        return InboxMiddleware(
            CID,
            run_id=self.run_id,
            drain=self.dispatch.drain_inbox,
            emit=self.emit,
            clock=self.clock,
            record_wait=self.waits.append,
        )

    def session(self, api_meta: dict | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            id="sv-inbox", session_id=CID, tenant_id=TENANT, user_id=USER, question="q", api_meta=api_meta
        )

    async def build(self, *, profile: str = "planned", inbox: Any = "default", api_meta: dict | None = None):
        backend = WorkspaceBackend(svid="sv-inbox", minio=_MemoryObjectStore(), file_dir=str(self.tmp_path))
        return await agent_factory.create_linsight_agent(
            self.session(api_meta),
            [],
            backend=backend,
            file_dir=str(self.tmp_path),
            checkpointer=self.checkpointer,
            profile=profile,
            inbox=self.middleware() if inbox == "default" else inbox,
        )

    async def run(self, agent) -> dict:
        return await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [("user", "写一份报告")]},
                config={"configurable": {"thread_id": CID}, "recursion_limit": 40},
            ),
            timeout=20,
        )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Env:
    return _Env(monkeypatch, tmp_path)


def _steer_texts(messages: list[BaseMessage]) -> list[str]:
    return [
        str(m.content) for m in messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("source") == "inbox"
    ]


def _capture_deep_agent(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record the keyword arguments the factory hands to ``create_deep_agent``."""
    import deepagents

    captured: dict = {}
    real = deepagents.create_deep_agent

    def fake(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(deepagents, "create_deep_agent", fake)
    return captured


def _inbox_instances(middleware: list | None) -> list:
    return [m for m in middleware or [] if isinstance(m, InboxMiddleware)]


# --------------------------------------------------------------- AC-15


async def test_injected_before_next_model_call(env: _Env):
    """A message sent during model call 0 is in the input of model call 1, behind the tool result."""
    await env.start()

    async def on_call(index: int) -> None:
        if index == 0:
            await env.steer("第 2 步改成写 PPT")

    env.model.on_call = on_call
    await env.run(await env.build())

    assert _steer_texts(env.model.inputs[0]) == []
    call_1 = env.model.inputs[1]
    assert _steer_texts(call_1) == ["第 2 步改成写 PPT"]
    tool_index = next(i for i, m in enumerate(call_1) if isinstance(m, ToolMessage) and m.name == "write_todos")
    steer_index = next(i for i, m in enumerate(call_1) if m.additional_kwargs.get("source") == INBOX_SOURCE)
    assert tool_index < steer_index
    # Nothing follows the injected message: it does not split a batch of tool messages.
    assert steer_index == len(call_1) - 1
    assert isinstance(call_1[steer_index - 1], ToolMessage)


async def test_does_not_split_a_batch_of_tool_messages(env: _Env):
    """Two parallel tool calls: both results come first, then the injected message."""
    env.model.script = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "write_todos", "args": {"todos": TODOS}, "id": "p1", "type": "tool_call"},
                {"name": "ls", "args": {"path": "/"}, "id": "p2", "type": "tool_call"},
            ],
        ),
        AIMessage(content="done"),
    ]
    await env.start()

    async def on_call(index: int) -> None:
        if index == 0:
            await env.steer("换个方向")

    env.model.on_call = on_call
    await env.run(await env.build())

    kinds = [type(m).__name__ for m in env.model.inputs[1]]
    assert kinds[-3:] == ["ToolMessage", "ToolMessage", "HumanMessage"]


# --------------------------------------------------------------- AC-16


async def test_order_and_exactly_once(env: _Env):
    """Several messages are injected in the order they entered the inbox, each one once."""
    await env.start()

    async def on_call(index: int) -> None:
        if index == 0:
            for text in ("第一条", "第二条", "第三条"):
                await env.steer(text)
        if index == 1:
            await env.steer("第四条")

    env.model.on_call = on_call
    final = await env.run(await env.build())

    assert _steer_texts(env.model.inputs[1]) == ["第一条", "第二条", "第三条"]
    assert _steer_texts(env.model.inputs[2]) == ["第一条", "第二条", "第三条", "第四条"]
    assert _steer_texts(final["messages"]) == ["第一条", "第二条", "第三条", "第四条"]
    assert await env.dispatch.inbox_length(CID) == 0


async def test_message_read_by_the_runner_is_not_delivered_again(env: _Env):
    """``drain_inbox`` is exactly-once: what the runner of a relay run took, the middleware never sees."""
    await env.start()
    await env.steer("接力运行的输入")
    taken = await env.dispatch.drain_inbox(CID)
    assert [m["text"] for m in taken] == ["接力运行的输入"]

    async def on_call(index: int) -> None:
        if index == 0:
            await env.steer("之后才到的消息")

    env.model.on_call = on_call
    final = await env.run(await env.build())

    assert _steer_texts(final["messages"]) == ["之后才到的消息"]


# --------------------------------------------------------------- AC-14


async def test_steer_read_event(env: _Env):
    """One ``steer_read`` with the message id per message, plus the wait for the metric."""
    await env.start()
    ids: list[str] = []

    async def on_call(index: int) -> None:
        if index == 0:
            ids.append(await env.steer("甲"))
            env.clock.now += 2
            ids.append(await env.steer("乙"))
            env.clock.now += 3

    env.model.on_call = on_call
    await env.run(await env.build())

    assert env.events == [
        {"type": "steer_read", "data": {"message_id": ids[0]}, "run_id": env.run_id},
        {"type": "steer_read", "data": {"message_id": ids[1]}, "run_id": env.run_id},
    ]
    assert env.waits == [pytest.approx(5000.0), pytest.approx(3000.0)]


async def test_steer_read_failure_does_not_lose_the_message(env: _Env):
    """The message already left the inbox, so a failing event sink must not stop the injection."""
    await env.start()

    async def broken(event: dict) -> None:
        raise ConnectionError("redis is away")

    env.emit = broken  # type: ignore[method-assign]

    async def on_call(index: int) -> None:
        if index == 0:
            await env.steer("仍然要送达")

    env.model.on_call = on_call
    final = await env.run(await env.build())

    assert _steer_texts(final["messages"]) == ["仍然要送达"]


# --------------------------------------------------------------- AC-18


async def test_late_message_stays_queued(env: _Env):
    """A message sent during the LAST model call is not read; it stays for the relay run."""
    await env.start()
    late: list[str] = []

    async def on_call(index: int) -> None:
        if index == 2:
            late.append(await env.steer("这条在最后一次模型调用期间发出"))

    env.model.on_call = on_call
    final = await env.run(await env.build())

    assert env.model.calls == 3
    assert _steer_texts(final["messages"]) == []
    assert env.events == []
    assert await env.dispatch.inbox_length(CID) == 1
    left = await env.dispatch.drain_inbox(CID)
    assert [(m["message_id"], m["text"]) for m in left] == [(late[0], "这条在最后一次模型调用期间发出")]


# --------------------------------------------------------------- mount rules


async def test_not_in_subagents(env: _Env, monkeypatch: pytest.MonkeyPatch):
    """Main graph only (design §5 pitfall 5): no subagent middleware list holds it."""
    captured = _capture_deep_agent(monkeypatch)
    inbox = env.middleware()
    await env.build(inbox=inbox)

    assert _inbox_instances(captured["middleware"]) == [inbox]
    assert captured["subagents"], "the factory must still build its subagents"
    for subagent in captured["subagents"]:
        assert _inbox_instances(subagent.get("middleware")) == []


async def test_not_in_unattended(env: _Env, monkeypatch: pytest.MonkeyPatch):
    """AC-23: an Open API run gets no inbox middleware, even when the caller passes one."""
    captured = _capture_deep_agent(monkeypatch)
    await env.build(api_meta={"channel": OPEN_API_CHANNEL})
    assert _inbox_instances(captured["middleware"]) == []


@pytest.mark.parametrize("profile", ["planned", "direct"])
async def test_not_mounted_without_an_inbox(env: _Env, monkeypatch: pytest.MonkeyPatch, profile: str):
    """Legacy callers pass nothing: the middleware list is the one of today."""
    captured = _capture_deep_agent(monkeypatch)
    await env.build(profile=profile, inbox=None)
    without = [type(m).__name__ for m in captured["middleware"]]
    assert "InboxMiddleware" not in without

    captured.clear()
    await env.build(profile=profile)
    with_inbox = [type(m).__name__ for m in captured["middleware"]]
    assert [name for name in with_inbox if name != "InboxMiddleware"] == without
    assert with_inbox.count("InboxMiddleware") == 1


# --------------------------------------------------------------- AC-19


async def test_works_in_direct_profile(env: _Env, monkeypatch: pytest.MonkeyPatch):
    """The production ``DirectRunner`` wiring: Redis stream, event hooks and the metric all see the read."""
    monkeypatch.setattr(direct_run, "_HOOK_FACTORIES", [])
    emitted: list = []
    monkeypatch.setattr(
        run_metrics, "emit_run_metric", lambda metrics, status, size=None: emitted.append((metrics, status))
    )
    env.model.script = [_call("ls", {"path": "/"}, "d1"), AIMessage(content="好的，已调整")]
    stream = RunEventStream(env.redis, wall_clock=env.clock)
    store = _MemoryObjectStore()

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0.002)

    async def no_admission(ctx: DirectRunContext) -> None:
        return None

    async def assemble(ctx: DirectRunContext, file_dir: str) -> ToolAssembly:
        return ToolAssembly(tools=[])

    async def build_input(ctx: DirectRunContext) -> dict:
        return {"messages": [{"role": "user", "content": ctx.text}]}

    async def object_store() -> _MemoryObjectStore:
        return store

    runner = DirectRunner(
        redis=env.redis,
        clock=env.clock,
        sleep=sleep,
        stream=stream,
        lease=RunLeaseService(env.redis, clock=env.clock),
        dispatch=env.dispatch,
        checkpointer=env.checkpointer,
        admit=no_admission,
        assemble=assemble,
        build_input=build_input,
        object_store=object_store,
        file_dir_for=lambda ctx: str(env.tmp_path / "cache"),
        recursion_limit=40,
    )
    await env.start("你好")
    ids: list[str] = []

    async def on_call(index: int) -> None:
        if index == 0:
            ids.append(await env.steer("顺便用英文回答"))
            env.clock.now += 1.5

    env.model.on_call = on_call
    hook_events: list[dict] = []
    ctx = DirectRunContext(conversation_id=CID, run_id=env.run_id, tenant_id=TENANT, user_id=USER, text="你好")
    outcome = await asyncio.wait_for(
        direct_run.execute_direct_run(ctx, runner=runner, on_event=[hook_events.append]), timeout=20
    )

    assert outcome.status == "finished"
    assert _steer_texts(env.model.inputs[1]) == ["顺便用英文回答"]
    stream_events = [event async for event in stream.read(CID)]
    read = [event for event in stream_events if event["type"] == "steer_read"]
    assert [event["data"] for event in read] == [{"message_id": ids[0]}]
    assert [event["data"] for event in hook_events if event["type"] == "steer_read"] == [{"message_id": ids[0]}]
    # The user's own words are not part of the answer text.
    text = "".join(str(event["data"].get("text", "")) for event in stream_events if event["type"] == "text")
    assert "顺便用英文回答" not in text
    assert "好的，已调整" in text
    metrics, status = emitted[-1]
    assert status == "finished"
    assert metrics.steer_waits_ms == [pytest.approx(1500.0)]


# --------------------------------------------------------------- state


async def test_injected_message_persisted_in_state(env: _Env):
    """The injected message is part of the checkpointed conversation, in its place."""
    await env.start()
    ids: list[str] = []

    async def on_call(index: int) -> None:
        if index == 0:
            ids.append(await env.steer("第 2 步改成写 PPT"))

    env.model.on_call = on_call
    agent = await env.build()
    await env.run(agent)

    snapshot = await agent.aget_state({"configurable": {"thread_id": CID}})
    messages = snapshot.values["messages"]
    steer = [m for m in messages if isinstance(m, HumanMessage) and m.additional_kwargs.get("source") == INBOX_SOURCE]
    assert [str(m.content) for m in steer] == ["第 2 步改成写 PPT"]
    assert steer[0].additional_kwargs["message_id"] == ids[0]
    position = messages.index(steer[0])
    assert isinstance(messages[position - 1], ToolMessage)
    assert isinstance(messages[position + 1], AIMessage)


# --------------------------------------------------------------- planned executor wiring


async def test_planned_executor_builds_the_middleware_only_on_the_unified_channel(env: _Env):
    """``task_exec`` hands the factory an inbox only while the execution is a unified run."""
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
    assert task._inbox_middleware() is None

    await env.start()
    message_id = await env.steer("改成三步")
    task._unified = SimpleNamespace(
        conversation_id=CID, run_id=env.run_id, dispatch=env.dispatch, emit=env.emit, lease_lost=True
    )
    inbox = task._inbox_middleware()

    assert isinstance(inbox, InboxMiddleware)
    # A run that lost its lease no longer holds the conversation: the inbox
    # belongs to the new holder, so this run takes nothing from it.
    assert await inbox.abefore_model({"messages": []}, None) is None
    assert env.events == []
    task._unified.lease_lost = False
    update = await inbox.abefore_model({"messages": []}, None)
    assert [str(m.content) for m in update["messages"]] == ["改成三步"]
    assert env.events == [{"type": "steer_read", "data": {"message_id": message_id}, "run_id": env.run_id}]
    assert await inbox.abefore_model({"messages": []}, None) is None

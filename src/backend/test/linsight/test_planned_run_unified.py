"""The ``planned`` run on the unified channel (F004 T033/T034; design 决策 3, 4, 9).

With the unified-runtime switch on for the tenant, a deep-research run executed
by the Linsight worker

* holds the conversation through the short lease of ``run_lease`` (renewed
  while it runs) instead of the fixed 4-hour run lock,
* writes unified events to the conversation's event stream,
* stops when the run's stop flag is set,
* ends through ``RunDispatchService.on_run_finished`` (idle or relay),

while the legacy WebSocket list keeps receiving the event types it gets today.
The worker also executes ``direct`` relay runs taken from its queue.

The agent is the REAL graph of ``create_linsight_agent`` driven by a scripted
model. Redis is fakeredis; the database is replaced by in-memory fakes.
"""

from __future__ import annotations

import asyncio
import importlib
import pickle
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.core.context.tenant import current_tenant_id
from bisheng.linsight import worker as worker_mod
from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.services import agent_factory
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, TaskAlreadyInProgressError
from bisheng.linsight.worker import LinsightQueue, ScheduleCenterProcess, encode_queue_item
from bisheng.workstation.domain.services import run_lease
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService, inbox_key
from bisheng.workstation.domain.services.run_lease import RunLeaseService

CHAT = "chat-9001"
SVID = "sv-9001"
TENANT = 7
TODOS = [{"content": "1. 收集资料", "status": "in_progress"}]
TODOS_DONE = [{"content": "1. 收集资料", "status": "completed"}]


def _call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class _PlannedUnifiedModel(BaseChatModel):
    """Replays a script. The item ``"hold"`` waits until the run is cancelled."""

    script: list[Any]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _get_ls_params(self, stop: Any = None, **kwargs: Any) -> dict[str, str]:
        # A provider of its own (design §5 pitfall 17).
        return {"ls_provider": "f004-planned-unified", "ls_model_name": "scripted"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> _PlannedUnifiedModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> Any:
        raise AssertionError("the planned run streams asynchronously")

    async def _agenerate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> Any:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if item == "hold":
            await asyncio.sleep(60)
            raise AssertionError("the stopped run was not cancelled")
        return ChatResult(generations=[ChatGeneration(message=item)])


class FakeClock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


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

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]


class _FakeStateManager:
    """What ``LinsightStateMessageManager`` does for a run, kept in memory.

    ``pushes`` is the legacy WebSocket list (``linsight_tasks:{svid}:messages``).
    """

    def __init__(self, session: LinsightSessionVersion) -> None:
        self.session = session
        self.pushes: list[Any] = []
        self.tasks: dict[str, Any] = {}

    async def push_message(self, message: Any) -> None:
        self.pushes.append(message)

    async def set_session_version_info(self, session_model: Any) -> None:
        self.session = session_model

    async def get_session_version_info(self) -> Any:
        return self.session

    async def set_execution_tasks(self, tasks: list[Any]) -> None:
        for task in tasks:
            self.tasks[task.id] = task

    async def get_execution_tasks(self) -> list[Any]:
        return list(self.tasks.values())

    async def update_execution_task_status(self, task_id: str, status: Any, **kwargs: Any) -> dict:
        task = self.tasks.get(task_id)
        if task is None:
            return {}
        task.status = status
        return task.model_dump()

    async def add_execution_task_step(self, task_id: str, step: Any) -> None:
        return None

    def types(self) -> list[str]:
        return [str(message.event_type.value) for message in self.pushes]


def _version(**fields: Any) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id=SVID, session_id=CHAT, user_id=1, tenant_id=TENANT, question="写一份报告", **fields
    )


class _Env:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path, *, unified: bool = True) -> None:
        from bisheng.core.config.settings import LinsightConf

        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.clock = FakeClock()
        self.redis = fakeredis.aioredis.FakeRedis()
        self.saver = InMemorySaver()
        self.store = _MemoryObjectStore()
        self.version = _version()
        self.state = _FakeStateManager(self.version)
        self.lease = RunLeaseService(self.redis, clock=self.clock)
        self.stream = RunEventStream(self.redis, wall_clock=self.clock)
        self.relays: list[dict] = []
        self.finished: list[tuple[str, str | None]] = []
        self.expired: list[tuple[str, str]] = []
        self.ticks = 0
        self.on_tick: Any = None
        self.rows: dict[str, Any] = {}

        conf = SimpleNamespace(get_linsight_conf=lambda: LinsightConf())
        monkeypatch.setattr(agent_factory, "settings", conf)
        monkeypatch.setattr(task_exec, "settings", conf)
        monkeypatch.setattr(task_exec, "_unified_runtime_enabled", AsyncMock(return_value=unified))
        monkeypatch.setattr(task_exec, "_run_redis", AsyncMock(return_value=self.redis))
        monkeypatch.setattr(task_exec, "build_run_dispatch", self._build_dispatch)
        monkeypatch.setattr(task_exec, "get_minio_storage", AsyncMock(return_value=self.store))
        # The legacy lock fails open without Redis (its documented behaviour).
        monkeypatch.setattr(
            importlib.import_module("bisheng.core.cache.redis_manager"),
            "get_redis_client",
            AsyncMock(side_effect=RuntimeError("no redis")),
        )
        monkeypatch.setattr(
            "bisheng.linsight.domain.services.checkpointer.make_checkpointer", lambda *a, **k: self.saver
        )
        monkeypatch.setattr(
            task_exec.LinsightSessionVersionDao,
            "get_session_versions_by_session_id",
            AsyncMock(side_effect=lambda _sid: [self.version]),
        )
        monkeypatch.setattr(task_exec.LinsightWorkbenchImpl, "prepare_file_list", AsyncMock(return_value=[]))
        self.saved_versions: list[Any] = []
        monkeypatch.setattr(
            task_exec.LinsightSessionVersionDao,
            "insert_one",
            AsyncMock(side_effect=lambda version: self.saved_versions.append(version) or version),
        )
        monkeypatch.setattr(linsight_utils.ChatMessageDao, "aget_messages_by_chat_id", AsyncMock(return_value=[]))

        async def get_rows(session_version_id: str = None, **_: Any) -> list[Any]:
            return list(self.rows.values())

        async def create_rows(tasks: list[Any]) -> list[Any]:
            for task in tasks:
                self.rows[task.id] = task
            return tasks

        monkeypatch.setattr(task_exec.LinsightExecuteTaskDao, "get_by_session_version_id", get_rows)
        monkeypatch.setattr(task_exec.LinsightExecuteTaskDao, "batch_create_tasks", create_rows)

    async def _build_dispatch(self, redis: Any = None, clock: Any = None) -> RunDispatchService:
        dispatch = RunDispatchService(
            self.redis, clock=self.clock, enqueue_relay=self._enqueue, on_run_expired=self._on_expired
        )
        real_finish = dispatch.on_run_finished

        async def on_run_finished(conversation_id: str, run_id: str | None = None):
            self.finished.append((conversation_id, run_id))
            return await real_finish(conversation_id, run_id)

        dispatch.on_run_finished = on_run_finished
        return dispatch

    async def _enqueue(self, item: dict) -> None:
        self.relays.append(item)

    async def _on_expired(self, conversation_id: str, run_id: str) -> None:
        self.expired.append((conversation_id, run_id))

    async def _sleep(self, seconds: float) -> None:
        # One watcher tick: the fake clock moves by the requested time.
        self.clock.now += seconds
        self.ticks += 1
        if self.on_tick is not None:
            await self.on_tick(self.ticks)
        await asyncio.sleep(0.002)

    def task(self, run_id: str | None = None) -> LinsightWorkflowTask:
        task = LinsightWorkflowTask()
        task.session_version_id = SVID
        task.file_dir = str(self.tmp_path)
        task._state_manager = self.state
        task._get_session_model = AsyncMock(return_value=self.version)
        task._resolve_knowledge_block = AsyncMock(return_value=None)
        task._unified_clock = self.clock
        task._unified_sleep = self._sleep
        task._run_id_hint = run_id
        return task

    async def run(self, script: list[Any], *, run_id: str | None = None) -> tuple[LinsightWorkflowTask, bool]:
        """One fresh run: claim, stream, and the exit the stream's result calls for."""
        task = self.task(run_id)
        model = _PlannedUnifiedModel(script=script)
        self.monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
        async with task._acquire_session_run_lock():
            await task._enter_conversation_thread(self.version)
            backend = WorkspaceBackend(
                workspace_prefix=task._workspace_prefix(self.version), minio=self.store, file_dir=str(self.tmp_path)
            )
            agent = await agent_factory.create_linsight_agent(
                self.version, [], backend=backend, file_dir=str(self.tmp_path), checkpointer=self.saver
            )
            completed = await task._execute_agent_tasks(agent, self.version)
            if completed:
                await task._finish_unified_run(self.version)
            else:
                await task._handle_user_termination(self.version)
        return task, completed

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CHAT)]

    async def run_keys(self) -> list[bytes]:
        return [key async for key in self.redis.scan_iter("bisheng:run:*")]


SCRIPT = [
    _call("write_todos", {"todos": TODOS}, "c1"),
    _call("write_todos", {"todos": TODOS_DONE}, "c2"),
    AIMessage("研究完成"),
]


async def test_planned_writes_unified_events(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)

    task, completed = await env.run(SCRIPT)

    assert completed is True
    events = await env.events()
    types = [event["type"] for event in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert "plan" in types and "tool_call" in types and "text" in types
    # The run id of a planned run defaults to its session version id.
    assert {event["run_id"] for event in events} == {SVID}
    assert events[0]["data"]["profile"] == "planned"

    plans = [event["data"]["items"] for event in events if event["type"] == "plan"]
    assert [item["content"] for item in plans[0]] == ["1. 收集资料"]
    assert plans[0][0]["status"] == "in_progress" and plans[-1][0]["status"] == "completed"
    assert "".join(event["data"]["text"] for event in events if event["type"] == "text") == "研究完成"

    snapshot = await env.stream.snapshot(CHAT)
    assert snapshot["ended"] and snapshot["text"] == "研究完成"

    # Every exit goes through on_run_finished; with an empty inbox the conversation is idle.
    assert env.finished == [(CHAT, SVID)]
    assert (await env.lease.get_state(CHAT)).status == run_lease.STATUS_IDLE
    assert task._unified is None
    # The short driver lock is gone too: the next run of this version can start.
    assert not await env.redis.exists(f"{task_exec.LINSIGHT_RUN_LOCK_KEY_PREFIX}{SVID}")


async def test_planned_run_takes_the_lease_of_the_send_entry_and_relays(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    dispatch = await env._build_dispatch()
    message = {"text": "写一份报告", "task_mode": True, "user_id": 1, "tenant_id": TENANT}
    started = await dispatch.submit(CHAT, message)
    assert started.disposition == "started" and started.profile == "planned"
    # A second message arrives while the run waits in the worker queue: it joins the inbox.
    queued = await dispatch.submit(CHAT, {**message, "text": "再加一节"})
    assert queued.disposition == "queued"
    env.finished.clear()

    await env.run(SCRIPT, run_id=started.run_id)

    events = await env.events()
    assert {event["run_id"] for event in events} == {started.run_id}
    assert env.finished == [(CHAT, started.run_id)]
    # The unread message starts a relay run handed to the worker queue, with the tenant.
    assert len(env.relays) == 1
    relay = env.relays[0]
    assert relay["conversation_id"] == CHAT and relay["tenant_id"] == TENANT and relay["profile"] == "planned"
    state = await env.lease.get_state(CHAT)
    assert state.status == run_lease.STATUS_RUNNING and state.run_id == relay["run_id"]
    assert await env.redis.llen(inbox_key(CHAT)) == 1


async def test_planned_renews_and_stops(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    renewals: list[float] = []
    real_renew = RunLeaseService.renew

    async def counting_renew(self, conversation_id: str, run_id: str) -> bool:
        renewals.append(env.clock.now)
        return await real_renew(self, conversation_id, run_id)

    monkeypatch.setattr(RunLeaseService, "renew", counting_renew)
    lease_seen: dict[str, Any] = {}

    async def on_tick(tick: int) -> None:
        if tick == 25:
            # 25 one-second polls: the lease (30 s) would have lapsed without renewals.
            lease_seen["valid"] = await env.lease.is_lease_valid(CHAT)
            lease_seen["lock_ttl"] = await env.redis.ttl(f"{task_exec.LINSIGHT_RUN_LOCK_KEY_PREFIX}{SVID}")
            await env.lease.request_stop(SVID, CHAT)

    env.on_tick = on_tick

    task, completed = await env.run([_call("write_todos", {"todos": TODOS}, "c1"), "hold"])

    assert completed is False
    assert lease_seen["valid"] is True
    # The driver lock is a short lease as well, not the fixed 4-hour lock.
    assert 0 < lease_seen["lock_ttl"] <= run_lease.LEASE_SECONDS
    # One renewal when the run claims the conversation, then one every 10 s.
    assert len(renewals) >= 3
    assert all(
        later - earlier >= run_lease.RENEW_INTERVAL_SECONDS for earlier, later in zip(renewals[1:], renewals[2:])
    )

    events = await env.events()
    assert events[-1]["type"] == "run_stopped" and events[-1]["data"] == {"reason": "user"}
    assert env.finished == [(CHAT, SVID)]
    assert (await env.lease.get_state(CHAT)).status == run_lease.STATUS_IDLE
    # The run record and the legacy channel see the stop exactly as today.
    assert env.state.session.status == SessionVersionStatusEnum.TERMINATED
    assert env.state.types()[-1] == "task_terminated"


async def test_planned_run_parks_on_ask_user(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    task = env.task()
    async with task._acquire_session_run_lock():
        # What _handle_need_user_input records when the stream ended on an interrupt.
        task._waiting_for_input = True

    state = await env.lease.get_state(CHAT)
    assert state.status == run_lease.STATUS_WAITING and state.run_id == SVID and state.lease_until_ms == 0
    assert env.finished == []

    # The answer resumes the SAME run: no run_started (it would clear the stream).
    resumed = env.task()
    resumed._unified_resume = True
    async with resumed._acquire_session_run_lock():
        assert (await env.lease.get_state(CHAT)).status == run_lease.STATUS_RUNNING
        await resumed._finish_unified_run(env.version)
    types = [event["type"] for event in await env.events()]
    assert types == ["run_started", "ask_user_answered", "run_finished"]
    assert env.finished == [(CHAT, SVID)]


async def test_second_driver_of_the_same_run_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    first = env.task()
    async with first._acquire_session_run_lock():
        with pytest.raises(TaskAlreadyInProgressError):
            async with env.task()._acquire_session_run_lock():
                raise AssertionError("two workers drove the same run")
        # The rejected worker must not have ended the run it does not own.
        assert env.finished == []
        assert (await env.lease.get_state(CHAT)).status == run_lease.STATUS_RUNNING


async def test_failure_writes_run_failed_before_the_conversation_is_released(monkeypatch: pytest.MonkeyPatch, tmp_path):
    env = _Env(monkeypatch, tmp_path)
    task = env.task()
    seen: dict[str, Any] = {}
    real_build = env._build_dispatch

    async def build(redis: Any = None, clock: Any = None) -> RunDispatchService:
        dispatch = await real_build(redis, clock)
        inner = dispatch.on_run_finished

        async def on_run_finished(conversation_id: str, run_id: str | None = None):
            seen["types"] = [event["type"] for event in await env.events()]
            return await inner(conversation_id, run_id)

        dispatch.on_run_finished = on_run_finished
        return dispatch

    monkeypatch.setattr(task_exec, "build_run_dispatch", build)
    with pytest.raises(ValueError):
        async with task._acquire_session_run_lock():
            raise ValueError("model exploded")

    assert seen["types"] == ["run_started", "run_failed"]
    failed = (await env.events())[-1]["data"]
    assert set(failed) >= {"code", "reason", "detail", "reference_id"}
    assert (await env.lease.get_state(CHAT)).status == run_lease.STATUS_IDLE


async def test_legacy_ws_still_receives(monkeypatch: pytest.MonkeyPatch, tmp_path):
    legacy = _Env(monkeypatch, tmp_path / "off", unified=False)
    (tmp_path / "off").mkdir()
    await legacy.run(SCRIPT)
    # Switch off: nothing of the unified runtime is written.
    assert await legacy.run_keys() == []
    assert legacy.finished == []
    assert legacy.version.api_meta is None

    unified = _Env(monkeypatch, tmp_path / "on", unified=True)
    (tmp_path / "on").mkdir()
    await unified.run(SCRIPT)
    assert await unified.events()

    # The legacy WebSocket list receives the same event types, in the same order.
    assert unified.state.types() == legacy.state.types()
    assert {"task_generate", "task_start", "task_end", "task_execute_step"} <= set(unified.state.types())

    def generated(env: _Env) -> list[list[str]]:
        return [
            [task["task_data"]["name"] for task in message.data["tasks"]]
            for message in env.state.pushes
            if message.event_type.value == "task_generate"
        ]

    assert generated(unified) == generated(legacy)


async def test_expired_run_marks_the_record_failed(monkeypatch: pytest.MonkeyPatch):
    redis = fakeredis.aioredis.FakeRedis()
    version = _version(status=SessionVersionStatusEnum.IN_PROGRESS)
    saved: list[Any] = []
    monkeypatch.setattr(task_exec, "_run_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(task_exec.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=version))
    monkeypatch.setattr(
        task_exec.LinsightSessionVersionDao, "insert_one", AsyncMock(side_effect=lambda v: saved.append(v) or v)
    )
    monkeypatch.setattr(task_exec.LinsightExecuteTaskDao, "batch_update_status_by_session_version_id", AsyncMock())
    announce = AsyncMock()
    monkeypatch.setattr(linsight_utils, "announce_stranded_session_failure", announce)

    await task_exec.mark_run_expired(CHAT, SVID)

    events = [event async for event in RunEventStream(redis).read(CHAT)]
    assert [event["type"] for event in events] == ["run_failed"]
    assert events[0]["run_id"] == SVID
    assert events[0]["data"]["reason"] == "lease_expired" and events[0]["data"]["code"] == 11091
    assert saved and saved[0].status == SessionVersionStatusEnum.FAILED
    assert saved[0].output_result["error_code"] == 11091
    announce.assert_awaited_once_with(SVID)

    # A record that already ended is left alone; the event is still written.
    saved.clear()
    version.status = SessionVersionStatusEnum.COMPLETED
    await task_exec.mark_run_expired(CHAT, SVID)
    assert saved == []


# ---------------------------------------------------------------------------
# Worker queue
# ---------------------------------------------------------------------------


class _FakeRedisList:
    """The list slice of ``RedisClient`` the worker queue uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list] = {}

    async def arpush(self, key, value, expiration=3600):
        self.lists.setdefault(key, []).append(pickle.dumps(value))

    async def ablpop(self, key, timeout=0):
        items = self.lists.get(key, [])
        return pickle.loads(items.pop(0)) if items else None

    async def alrange(self, key, start=0, end=-1):
        return [pickle.loads(value) for value in self.lists.get(key, [])]

    async def allen(self, key):
        return len(self.lists.get(key, []))


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = _FakeRedisList()
    monkeypatch.setattr(worker_mod, "get_redis_client", AsyncMock(return_value=client))
    # The worker checks its permission runtime before a run, like the planned path does.
    monkeypatch.setattr(task_exec, "ensure_linsight_permission_runtime", AsyncMock(return_value={}))
    return client


def _make_worker(fake_redis: _FakeRedisList) -> ScheduleCenterProcess:
    worker = ScheduleCenterProcess()
    worker.queue = LinsightQueue("queue", namespace="linsight", redis=fake_redis)
    worker.max_concurrency = 5
    worker.semaphore = asyncio.Semaphore(5)
    node_manager = MagicMock()
    node_manager.node_id = "node-test"
    node_manager.register_task_ownership = AsyncMock()
    worker.node_manager = node_manager
    return worker


def _relay_item(**overrides: Any) -> dict:
    item = {
        "conversation_id": CHAT,
        "run_id": "run-relay",
        "profile": "direct",
        "relay": True,
        "tenant_id": TENANT,
        "user_id": 1,
        "message_id": "m-2",
        "task_mode": False,
        "tools": [],
        "skills": [],
        "knowledge": [],
        "files": [],
    }
    item.update(overrides)
    return item


async def _drain(worker: ScheduleCenterProcess) -> None:
    for _ in range(20):
        await asyncio.sleep(0)
        if worker.semaphore._value == worker.max_concurrency:
            return


async def test_worker_runs_direct_relay(monkeypatch: pytest.MonkeyPatch, fake_redis):
    worker = _make_worker(fake_redis)
    calls: list[dict] = []

    async def fake_execute(run_ctx: dict, **_: Any) -> None:
        calls.append(run_ctx)

    monkeypatch.setattr("bisheng.workstation.domain.services.direct_run.execute_direct_run", fake_execute)
    planned = AsyncMock()
    monkeypatch.setattr(worker_mod.LinsightWorkflowTask, "async_run", planned)
    session_lookup = AsyncMock()
    monkeypatch.setattr(worker_mod.LinsightSessionVersionDao, "get_by_id", session_lookup)

    # The enqueue function RunDispatchService is wired with puts the relay run into the worker queue.
    await worker_mod.enqueue_relay_run(_relay_item())
    await worker.semaphore.acquire()
    spawned = await worker.process_one_item()
    await _drain(worker)

    assert spawned is True
    assert len(calls) == 1
    assert calls[0]["conversation_id"] == CHAT and calls[0]["run_id"] == "run-relay" and calls[0]["relay"] is True
    # A direct run has no session version: no lookup, no ownership key, no planned executor.
    planned.assert_not_called()
    session_lookup.assert_not_called()
    worker.node_manager.register_task_ownership.assert_not_called()
    # The concurrency slot is released when the relay run ends.
    assert worker.semaphore._value == worker.max_concurrency


async def test_queue_item_restores_tenant(monkeypatch: pytest.MonkeyPatch, fake_redis):
    worker = _make_worker(fake_redis)
    seen: list[Any] = []

    async def fake_execute(run_ctx: dict, **_: Any) -> None:
        seen.append(current_tenant_id.get())

    monkeypatch.setattr("bisheng.workstation.domain.services.direct_run.execute_direct_run", fake_execute)
    token = current_tenant_id.set(None)
    try:
        await worker_mod.enqueue_relay_run(_relay_item())
        await worker.semaphore.acquire()
        assert await worker.process_one_item() is True
        await _drain(worker)
        # The tenant of the queue item is in place while the run executes ...
        assert seen == [TENANT]
        # ... and does not leak into the worker loop.
        assert current_tenant_id.get() is None

        # An item without a tenant is never executed, and the slot is given back.
        await worker.queue.put({"type": "direct_relay", **_relay_item(tenant_id=None)})
        await worker.semaphore.acquire()
        assert await worker.process_one_item() is False
        assert seen == [TENANT]
        assert worker.semaphore._value == worker.max_concurrency

        # The enqueue function refuses an item without a tenant instead of queueing it.
        with pytest.raises(ValueError):
            await worker_mod.enqueue_relay_run(_relay_item(tenant_id=None))
    finally:
        current_tenant_id.reset(token)


async def test_planned_queue_item_carries_tenant_and_run_id(monkeypatch: pytest.MonkeyPatch, fake_redis):
    worker = _make_worker(fake_redis)
    captured: dict[str, Any] = {}

    async def fake_async_run(self, svid, tenant_id=None, run_id=None):
        captured.update(svid=svid, tenant_id=tenant_id, run_id=run_id)

    monkeypatch.setattr(worker_mod.LinsightWorkflowTask, "async_run", fake_async_run)
    session = MagicMock()
    session.status = SessionVersionStatusEnum.NOT_STARTED
    monkeypatch.setattr(worker_mod.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session))

    await worker.queue.put(encode_queue_item(SVID, tenant_id=TENANT, run_id="run-1"))
    await worker.semaphore.acquire()
    assert await worker.process_one_item() is True
    await _drain(worker)

    assert captured == {"svid": SVID, "tenant_id": TENANT, "run_id": "run-1"}
    # An item without a run id stays exactly the legacy item.
    assert "run_id" not in encode_queue_item(SVID, tenant_id=TENANT)


async def test_queue_position_probe(fake_redis):
    queue = LinsightQueue("queue", namespace="linsight", redis=fake_redis)
    # An empty queue: a worker takes the run at once, no "queued" event.
    assert await worker_mod.planned_queue_position(CHAT, "run-1", {}) is None

    await queue.put(encode_queue_item("sv-a", tenant_id=TENANT))
    await queue.put(encode_queue_item("sv-b", resume=True, user_input="x", tenant_id=TENANT))
    await queue.put({"type": "direct_relay", **_relay_item()})
    # Two runs wait ahead (a resume item jumps the queue and is not counted).
    assert await worker_mod.planned_queue_position(CHAT, "run-1", {}) == 3


async def test_relay_run_that_cannot_start_gives_the_conversation_back(monkeypatch: pytest.MonkeyPatch, fake_redis):
    redis = fakeredis.aioredis.FakeRedis()
    fake_redis.async_connection = redis
    lease = RunLeaseService(redis)
    assert (await lease.acquire(CHAT, "run-relay", "direct")).acquired
    worker = _make_worker(fake_redis)
    executed = AsyncMock()
    monkeypatch.setattr("bisheng.workstation.domain.services.direct_run.execute_direct_run", executed)
    monkeypatch.setattr(
        task_exec, "ensure_linsight_permission_runtime", AsyncMock(side_effect=RuntimeError("runtime not ready"))
    )

    await worker_mod.enqueue_relay_run(_relay_item())
    await worker.semaphore.acquire()
    assert await worker.process_one_item() is True
    await _drain(worker)

    executed.assert_not_called()
    assert (await lease.get_state(CHAT)).status == run_lease.STATUS_IDLE
    events = [event async for event in RunEventStream(redis).read(CHAT)]
    assert [event["type"] for event in events] == ["run_started", "run_failed"]
    assert events[-1]["run_id"] == "run-relay"
    assert worker.semaphore._value == worker.max_concurrency


async def test_planned_relay_is_failed_visibly(monkeypatch: pytest.MonkeyPatch, fake_redis):
    redis = fakeredis.aioredis.FakeRedis()
    fake_redis.async_connection = redis
    monkeypatch.setattr(task_exec, "_run_redis", AsyncMock(return_value=redis))
    dispatch = RunDispatchService(redis, enqueue_relay=worker_mod.enqueue_relay_run)
    message = {"text": "先问一句", "task_mode": False, "user_id": 1, "tenant_id": TENANT}
    first = await dispatch.submit(CHAT, message)
    await dispatch.submit(CHAT, {**message, "text": "改成深度研究", "task_mode": True})
    # The direct run ends with one unread deep-research message: a planned relay run is queued.
    finished = await dispatch.on_run_finished(CHAT, first.run_id)
    assert finished.profile == "planned"
    worker = _make_worker(fake_redis)
    planned = AsyncMock()
    monkeypatch.setattr(worker_mod.LinsightWorkflowTask, "async_run", planned)

    await worker.semaphore.acquire()
    assert await worker.process_one_item() is True
    await _drain(worker)

    planned.assert_not_called()
    events = [event async for event in RunEventStream(redis).read(CHAT)]
    assert [event["type"] for event in events] == ["run_started", "run_failed"]
    assert events[-1]["data"]["reason"] == "relay_not_supported" and events[-1]["run_id"] == finished.run_id
    # The conversation is free again and does not start the same relay run on the next send.
    assert (await RunLeaseService(redis).get_state(CHAT)).status == run_lease.STATUS_IDLE
    assert await redis.llen(inbox_key(CHAT)) == 0

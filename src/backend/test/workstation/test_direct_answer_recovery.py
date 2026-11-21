"""F004 T043 (P1 leftovers): the answer row of a direct run that no HTTP request owns.

* A relay run executes in the Linsight worker. The worker attaches the
  persistence projector and the steer hook, the run reports the inbox messages
  it takes as its input (``steer_read``), and it answers with the model of the
  conversation.
* A direct run whose process died is closed by whoever notices the lapsed
  lease: what it had written becomes a failed answer row, exactly once.

Redis is fakeredis, the message table is in memory, the agent is a stub graph
(no model call is needed to observe persistence).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.linsight import worker as linsight_worker
from bisheng.linsight.domain import task_exec
from bisheng.linsight.domain import utils as linsight_utils
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.workstation.domain.services import chat_service, direct_run, run_message_persist, run_send
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.direct_run import DirectRunner
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService
from test.workstation.run_persist_support import MessageTable

CID = "conv-recovery-1"
USER = 7
TENANT = 3


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class _StubGraph:
    """A graph that ends at once; records the input it was given."""

    def __init__(self) -> None:
        self.inputs: list[Any] = []

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=None):
        self.inputs.append(graph_input)
        return
        yield  # pragma: no cover - makes this an async generator


class _Env:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        self.clock = FakeClock()
        self.redis = fakeredis.aioredis.FakeRedis()
        self.table = MessageTable().install(monkeypatch)
        self.relays: list[dict] = []
        self.lease = RunLeaseService(self.redis, clock=self.clock)
        self.stream = RunEventStream(self.redis, wall_clock=self.clock)
        self.graph = _StubGraph()
        self.contexts: list[Any] = []
        self.tmp_path = tmp_path

        async def fake_redis():
            return self.redis

        monkeypatch.setattr(run_message_persist, "_redis", fake_redis)
        monkeypatch.setattr(task_exec, "_run_redis", fake_redis)
        monkeypatch.setattr(task_exec, "_find_run_record", AsyncMock(return_value=None))
        monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
        monkeypatch.setattr(chat_service, "_promote_generated_files", AsyncMock(return_value=[]))
        monkeypatch.setattr(linsight_utils, "build_prior_conversation_summary", AsyncMock(return_value=""))
        monkeypatch.setattr(direct_run, "_HOOK_FACTORIES", [])
        self.dispatch = RunDispatchService(
            self.redis, clock=self.clock, enqueue_relay=self._enqueue, on_run_expired=task_exec.mark_run_expired
        )

    async def _enqueue(self, item: dict) -> None:
        self.relays.append(item)

    def message(self, text: str) -> dict:
        return {"text": text, "task_mode": False, "user_id": USER, "tenant_id": TENANT}

    def runner(self) -> DirectRunner:
        async def build_agent(ctx, tools, checkpointer, file_dir):
            self.contexts.append(ctx)
            return self.graph

        async def assemble(ctx, file_dir):
            return SimpleNamespace(tools=[], failures=[])

        async def sleep(seconds: float) -> None:
            await asyncio.sleep(0.002)

        async def object_store():
            # The runner builds the workspace backend for every run; these tests
            # never touch files, so an inert stand-in is enough.
            return SimpleNamespace(bucket="bisheng", minio_client_sync=None)

        return DirectRunner(
            redis=self.redis,
            clock=self.clock,
            sleep=sleep,
            stream=self.stream,
            lease=self.lease,
            dispatch=self.dispatch,
            checkpointer=InMemorySaver(),
            admit=AsyncMock(),
            assemble=assemble,
            build_agent=build_agent,
            object_store=object_store,
            file_dir_for=lambda ctx: str(self.tmp_path / "cache"),
            recursion_limit=20,
        )

    async def start_direct(self, text: str = "第一条", sender: str = "模型一", model_id: str = "m1") -> str:
        """What the send entry does for a new direct run, without executing it."""
        result = await self.dispatch.submit(CID, self.message(text))
        assert result.disposition == "started"
        await run_message_persist.remember_direct_run(
            self.redis, CID, result.run_id, user_id=USER, tenant_id=TENANT, sender=sender, model_id=model_id
        )
        return result.run_id

    async def steer(self, text: str) -> tuple[str, Any]:
        """A message sent while the run holds the conversation, with its queued row."""
        rows: list[Any] = []

        async def save(result, _message):
            data = SimpleNamespace(text=text, files=None)
            user = SimpleNamespace(user_id=USER)
            extra = run_message_persist.steer_extra(result.run_id, result.message_id, queued=True)
            row = await self.table.ainsert_one(run_send._question_row(data, user, CID, extra))
            await run_message_persist.bind_steer_row(self.redis, CID, result.message_id, row.id, result.run_id)
            rows.append(row)

        result = await self.dispatch.submit(CID, self.message(text), on_queued=save)
        assert result.disposition == "queued"
        return result.message_id, rows[0]

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CID, None)]


@pytest.fixture
async def env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    e = _Env(monkeypatch, tmp_path)
    yield e
    await e.redis.aclose()


# ----------------------------------------------------------- relay runs


async def _run_relay_in_worker(env: _Env, monkeypatch: pytest.MonkeyPatch, item: dict) -> None:
    """Drive the worker's relay branch with the test's runner instead of the production one."""
    real_execute = direct_run.execute_direct_run
    runner = env.runner()

    async def execute(run_ctx, *, on_event=(), **_kwargs):
        return await real_execute(run_ctx, runner=runner, on_event=on_event)

    monkeypatch.setattr(direct_run, "execute_direct_run", execute)
    monkeypatch.setattr(linsight_worker, "settings", SimpleNamespace(openfga=SimpleNamespace(enabled=False)))
    fake_self = SimpleNamespace(_fail_relay_run=AsyncMock())
    await linsight_worker.ScheduleCenterProcess._run_direct_relay(fake_self, item)
    fake_self._fail_relay_run.assert_not_awaited()


async def test_worker_relay_run_saves_its_answer_row(env: _Env, monkeypatch: pytest.MonkeyPatch):
    first_run = await env.start_direct()
    message_id, steer_row = await env.steer("运行结束时才到的消息")
    await env.dispatch.on_run_finished(CID, first_run)
    item = env.relays[0]
    before = get_current_tenant_id()

    await _run_relay_in_worker(env, monkeypatch, dict(item))

    # Exactly one answer row, written by the worker, for the relay run.
    (answer,) = env.table.answers()
    assert env.table.extra(answer)["run_id"] == item["run_id"]
    assert answer.user_id == USER and answer.chat_id == CID
    # The relay item carries no model: the conversation's model is used and shown.
    assert answer.sender == "模型一"
    assert env.contexts[0].model_id == "m1"
    assert (await env.lease.get_state(CID)).status == rl.STATUS_IDLE
    assert get_current_tenant_id() == before


async def test_relay_run_reports_the_messages_it_takes_as_input(env: _Env, monkeypatch: pytest.MonkeyPatch):
    first_run = await env.start_direct()
    message_id, steer_row = await env.steer("运行结束时才到的消息")
    await env.dispatch.on_run_finished(CID, first_run)

    await _run_relay_in_worker(env, monkeypatch, dict(env.relays[0]))

    events = await env.events()
    assert [e["type"] for e in events] == ["run_started", "steer_read", "run_finished"]
    assert events[1]["data"] == {"message_id": message_id}
    # The mark of the row is cleared in the worker process (AC-14).
    assert env.table.extra(steer_row) == {"run_id": first_run, "steer_message_id": message_id}
    # The message is the input of the run, once.
    contents = [m["content"] for m in env.graph.inputs[0]["messages"]]
    assert sum("运行结束时才到的消息" in content for content in contents) == 1
    assert await env.dispatch.inbox_length(CID) == 0


async def test_relay_run_without_a_known_model_still_runs(env: _Env, monkeypatch: pytest.MonkeyPatch):
    """No direct run of this conversation was remembered (e.g. the key expired)."""
    result = await env.dispatch.submit(CID, env.message("第一条"))
    await env.steer("后来的消息")
    await env.dispatch.on_run_finished(CID, result.run_id)

    await _run_relay_in_worker(env, monkeypatch, dict(env.relays[0]))

    (answer,) = env.table.answers()
    assert answer.sender == ""
    assert env.contexts[0].model_id is None


# ------------------------------------------------------- expired direct runs


async def _write_partial_answer(env: _Env, run_id: str, text: str = "写到一半") -> None:
    await env.stream.append(CID, {"type": "run_started", "run_id": run_id, "data": {"profile": "direct"}})
    await env.stream.append(CID, {"type": "text", "run_id": run_id, "data": {"text": text}})


async def test_expired_direct_run_gets_a_failed_answer_row(env: _Env):
    run_id = await env.start_direct()
    await _write_partial_answer(env, run_id)
    env.clock.now += rl.LEASE_SECONDS + 1

    recovered = await env.dispatch.recover_expired(CID)

    assert recovered is not None and recovered.expired_run_id == run_id
    (answer,) = env.table.answers()
    content = json.loads(answer.message)
    assert content["msg"] == "写到一半"
    assert content["events"] == [{"type": "text", "content": "写到一半"}]
    extra = env.table.extra(answer)
    assert extra["run_id"] == run_id and extra["error"] is True
    assert extra["error_code"] == task_exec.EXECUTOR_GONE_ERROR_CODE
    assert extra["error_type"] == "lease_expired"
    assert answer.sender == "模型一" and answer.user_id == USER and answer.type == "end"
    # The event still reaches the stream, after the row.
    assert [e["type"] for e in await env.events()][-1] == "run_failed"
    assert (await env.lease.get_state(CID)).status == rl.STATUS_IDLE


async def test_expired_direct_run_is_saved_once(env: _Env):
    run_id = await env.start_direct()
    await _write_partial_answer(env, run_id)

    await asyncio.gather(*(task_exec.mark_run_expired(CID, run_id) for _ in range(3)))
    await task_exec.mark_run_expired(CID, run_id)

    assert len(env.table.answers()) == 1


async def test_no_second_row_when_the_run_saved_its_answer_before_it_died(env: _Env):
    run_id = await env.start_direct()
    await _write_partial_answer(env, run_id, "完整的回答")
    row = chat_service.build_daily_answer_row(
        user_id=USER, chat_id=CID, sender="模型一", db_content={"msg": "完整的回答", "events": []}
    )
    row.extra = json.dumps({"run_id": run_id})
    await env.table.ainsert_one(row)

    await task_exec.mark_run_expired(CID, run_id)

    assert len(env.table.answers()) == 1
    assert "error" not in env.table.extra(env.table.answers()[0])


async def test_run_that_wrote_nothing_does_not_inherit_the_previous_text(env: _Env):
    await _write_partial_answer(env, "run-older", "上一轮的回答")
    await env.stream.append(CID, {"type": "run_finished", "run_id": "run-older", "data": {}})
    run_id = await env.start_direct()

    await task_exec.mark_run_expired(CID, run_id)

    (answer,) = env.table.answers()
    assert json.loads(answer.message) == {"msg": "", "events": []}
    assert env.table.extra(answer)["run_id"] == run_id


async def test_expired_planned_run_gets_no_answer_row(env: _Env):
    """A planned run keeps its own run record; nothing was remembered for it here."""
    result = await env.dispatch.submit(CID, {**env.message("研究一下"), "task_mode": True})
    await _write_partial_answer(env, result.run_id)

    await task_exec.mark_run_expired(CID, result.run_id)

    assert env.table.answers() == []
    assert [e["type"] for e in await env.events()][-1] == "run_failed"


async def test_a_failing_row_write_does_not_block_the_expiry(env: _Env, monkeypatch: pytest.MonkeyPatch):
    run_id = await env.start_direct()
    await _write_partial_answer(env, run_id)
    monkeypatch.setattr(env.table, "rows", None)  # every table access now raises
    env.clock.now += rl.LEASE_SECONDS + 1

    recovered = await env.dispatch.recover_expired(CID)

    assert recovered is not None
    assert [e["type"] for e in await env.events()][-1] == "run_failed"
    assert (await env.lease.get_state(CID)).status == rl.STATUS_IDLE

"""F004: the unified stop (``POST /conversations/{id}/stop``, AC-29) and the
legacy deep-research terminate endpoint on the unified runtime (design §7,
待定事项 5).

A running run is stopped through its stop flag, in whichever process it
executes. A run without a coroutine (parked on a question, or still in the
worker queue) is ended by the request itself, so the conversation is idle and
the next message starts a new run instead of being taken as an answer.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.responses import ORJSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.task_exec import LINSIGHT_RUN_LOCK_KEY_PREFIX
from bisheng.workstation.api.endpoints import chat as chat_endpoint
from bisheng.workstation.domain.services import chat_service, run_message_persist, run_send
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService
from test.workstation.run_persist_support import MessageTable

OWNER = 7
TENANT = 3
CID = "conv-stop-1"
PREFIX = "/api/v1/workstation"
STOP = f"{PREFIX}/conversations/{CID}/stop"


def _handle(req, exc):
    if isinstance(exc, HTTPException):
        return ORJSONResponse(content={"status_code": exc.status_code, "status_message": exc.detail})
    return ORJSONResponse(content={"status_code": exc.code, "status_message": exc.message})


class _World:
    def __init__(self, redis: Any, table: MessageTable):
        self.redis = redis
        self.table = table
        self.stream = RunEventStream(redis)
        self.lease = RunLeaseService(redis)
        self.dispatch = RunDispatchService(redis, enqueue_relay=AsyncMock())
        self.user = SimpleNamespace(user_id=OWNER, user_name="owner", tenant_id=TENANT)
        self.sessions: dict[str, Any] = {CID: SimpleNamespace(chat_id=CID, user_id=OWNER, name="已有会话")}
        self.record: Any = None
        self.terminated: list[Any] = []

    def message(self, text: str, task_mode: bool = False) -> dict:
        return {"text": text, "task_mode": task_mode, "user_id": OWNER, "tenant_id": TENANT}

    async def start(self, task_mode: bool = False) -> str:
        result = await self.dispatch.submit(CID, self.message("第一条", task_mode))
        if not task_mode:
            await run_message_persist.remember_direct_run(
                self.redis, CID, result.run_id, user_id=OWNER, tenant_id=TENANT, sender="模型一", model_id="m1"
            )
        return result.run_id

    async def park(self, run_id: str, text: str = "先问一句") -> None:
        for event in (
            {"type": "run_started", "data": {}},
            {"type": "text", "data": {"text": text}},
            {"type": "ask_user", "data": {"call_id": "c1", "questions": [{"question": "要哪一种？"}]}},
        ):
            await self.stream.append(CID, {**event, "run_id": run_id})
        assert await self.lease.park(CID, run_id)

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CID, None)]

    async def state(self):
        return await self.lease.get_state(CID)


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    redis = fakeredis.aioredis.FakeRedis()
    w = _World(redis, MessageTable().install(monkeypatch))

    async def fake_redis():
        return redis

    async def get_session(cid):
        return w.sessions.get(cid)

    async def planned_record(conversation_id, run_id):
        return w.record

    async def terminate(record):
        w.terminated.append(record)

    monkeypatch.setattr(run_send, "_redis", fake_redis)
    monkeypatch.setattr(run_message_persist, "_redis", fake_redis)
    monkeypatch.setattr(run_send, "_dispatch_wiring", lambda: {"enqueue_relay": w.dispatch._enqueue_relay})
    monkeypatch.setattr(run_send, "_get_session", get_session)
    monkeypatch.setattr(run_send, "_planned_run_record", planned_record)
    monkeypatch.setattr(run_send, "_terminate_planned_record", terminate)
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
    monkeypatch.setattr(chat_service, "_promote_generated_files", AsyncMock(return_value=[]))
    yield w
    await redis.aclose()


@pytest.fixture
async def client(world: _World):
    app = FastAPI()
    for exc_type in (HTTPException, BaseErrorCode):
        app.add_exception_handler(exc_type, _handle)
    app.include_router(chat_endpoint.router, prefix=PREFIX)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: world.user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _stop(client: httpx.AsyncClient) -> dict:
    response = await client.post(STOP)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status_code"] == 200, body
    return body["data"]


# ----------------------------------------------------------------- endpoint


async def test_stop_is_for_the_owner_only(world: _World, client: httpx.AsyncClient):
    run_id = await world.start()
    world.user = SimpleNamespace(user_id=OWNER + 1, user_name="other", tenant_id=TENANT)

    response = await client.post(STOP)

    assert response.json()["status_code"] == UnAuthorizedError.Code
    assert not await world.lease.should_stop(run_id)
    # Same answer for a conversation that does not exist.
    missing = await client.post(f"{PREFIX}/conversations/nope/stop")
    assert missing.json()["status_code"] == UnAuthorizedError.Code


async def test_stop_without_a_run_does_nothing(world: _World, client: httpx.AsyncClient):
    assert await _stop(client) == {"run_id": None, "status": "idle"}
    assert await world.events() == []


async def test_stop_of_a_running_direct_run_sets_its_flag(world: _World, client: httpx.AsyncClient):
    run_id = await world.start()

    assert await _stop(client) == {"run_id": run_id, "status": "stopping"}

    # The run itself writes run_stopped and releases the conversation (AC-29).
    assert await world.lease.should_stop(run_id)
    assert (await world.state()).status == rl.STATUS_RUNNING
    assert world.table.answers() == []


async def test_stop_ends_a_parked_direct_run(world: _World, client: httpx.AsyncClient):
    run_id = await world.start()
    await world.park(run_id)

    assert await _stop(client) == {"run_id": run_id, "status": "stopped"}

    assert (await world.state()).status == rl.STATUS_IDLE
    assert [e["type"] for e in await world.events()][-1] == "run_stopped"
    # What the run had written is saved, marked like a stopped turn.
    (answer,) = world.table.answers()
    assert json.loads(answer.message)["msg"] == "先问一句"
    extra = world.table.extra(answer)
    assert extra["run_id"] == run_id and extra["error"] is True and extra["error_msg"] == "stream interrupted"
    assert answer.sender == "模型一"
    # The flag of a run nobody executes is not left behind.
    assert not await world.lease.should_stop(run_id)
    # The next message starts a new run; it is not taken as the answer.
    after = await world.dispatch.submit(CID, world.message("新的问题"))
    assert after.kind == "new_run" and after.run_id != run_id


async def test_second_stop_of_a_parked_run_writes_nothing_more(world: _World, client: httpx.AsyncClient):
    run_id = await world.start()
    await world.park(run_id)

    await _stop(client)
    assert await _stop(client) == {"run_id": None, "status": "idle"}

    assert len(world.table.answers()) == 1
    assert [e["type"] for e in await world.events()].count("run_stopped") == 1


async def test_stop_ends_a_parked_planned_run(world: _World, client: httpx.AsyncClient):
    run_id = await world.start(task_mode=True)
    await world.park(run_id)
    world.record = SimpleNamespace(id="svid-1", status=SessionVersionStatusEnum.WAITING_FOR_USER_INPUT)

    assert await _stop(client) == {"run_id": run_id, "status": "stopped"}

    assert (await world.state()).status == rl.STATUS_IDLE
    assert world.terminated == [world.record]
    assert [e["type"] for e in await world.events()][-1] == "run_stopped"
    # A deep-research run keeps its own record: no daily answer row.
    assert world.table.answers() == []


async def test_stop_takes_a_queued_planned_run_out(world: _World, client: httpx.AsyncClient):
    """Still in the worker queue: no worker holds the driver key, nobody would see the flag."""
    run_id = await world.start(task_mode=True)
    world.record = SimpleNamespace(id="svid-1", status=SessionVersionStatusEnum.NOT_STARTED)

    assert await _stop(client) == {"run_id": run_id, "status": "stopped"}

    assert world.terminated == [world.record]
    assert (await world.state()).status == rl.STATUS_IDLE
    assert not await world.lease.should_stop(run_id)


async def test_stop_of_an_executing_planned_run_leaves_the_release_to_the_worker(
    world: _World, client: httpx.AsyncClient
):
    run_id = await world.start(task_mode=True)
    world.record = SimpleNamespace(id="svid-1", status=SessionVersionStatusEnum.IN_PROGRESS)
    await world.redis.set(f"{LINSIGHT_RUN_LOCK_KEY_PREFIX}svid-1", run_id, ex=30)

    assert await _stop(client) == {"run_id": run_id, "status": "stopping"}

    assert await world.lease.should_stop(run_id)
    assert (await world.state()).status == rl.STATUS_RUNNING
    # The record is terminated as the deep-research stop does today.
    assert world.terminated == [world.record]


async def test_stop_of_a_dead_run_reports_it(world: _World, client: httpx.AsyncClient):
    run_id = await world.start()
    await world.redis.hset(rl.state_key(CID), rl.FIELD_LEASE_UNTIL, "1")

    assert await _stop(client) == {"run_id": run_id, "status": "expired"}

    assert (await world.state()).status == rl.STATUS_IDLE
    last = (await world.events())[-1]
    assert last["type"] == "run_failed" and last["run_id"] == run_id


# ------------------------------------------- legacy terminate endpoint


@pytest.fixture
def linsight_endpoint(monkeypatch: pytest.MonkeyPatch):
    from bisheng.linsight.api.endpoints import linsight as endpoint
    from bisheng.workstation.domain.services import workstation_service

    switch = {"on": True}

    async def enabled(tenant_id):
        return switch["on"]

    monkeypatch.setattr(workstation_service, "is_unified_runtime_enabled", enabled)
    endpoint.switch = switch
    return endpoint


def _version(svid: str = "svid-1") -> Any:
    return SimpleNamespace(
        id=svid, session_id=CID, tenant_id=TENANT, status=SessionVersionStatusEnum.WAITING_FOR_USER_INPUT
    )


async def test_legacy_terminate_frees_a_parked_conversation(world: _World, linsight_endpoint):
    run_id = await world.start(task_mode=True)
    await world.park(run_id)
    world.record = _version()

    await linsight_endpoint._request_unified_stop(world.record)

    assert (await world.state()).status == rl.STATUS_IDLE
    # The record is left to the endpoint's own termination, as before.
    assert world.terminated == []
    after = await world.dispatch.submit(CID, world.message("新的问题"))
    assert after.kind == "new_run"


async def test_legacy_terminate_ignores_a_run_of_another_version(world: _World, linsight_endpoint):
    run_id = await world.start(task_mode=True)
    await world.park(run_id)
    world.record = _version("svid-current")

    await linsight_endpoint._request_unified_stop(_version("svid-older"))

    state = await world.state()
    assert state.status == rl.STATUS_WAITING and state.run_id == run_id


async def test_legacy_terminate_with_the_switch_off_touches_nothing(
    world: _World, linsight_endpoint, monkeypatch: pytest.MonkeyPatch
):
    run_id = await world.start(task_mode=True)
    await world.park(run_id)
    world.record = _version()
    linsight_endpoint.switch["on"] = False
    stop = AsyncMock()
    monkeypatch.setattr(run_send, "stop_conversation_run", stop)

    await linsight_endpoint._request_unified_stop(world.record)

    stop.assert_not_awaited()
    assert (await world.state()).status == rl.STATUS_WAITING


async def test_legacy_terminate_survives_a_failing_unified_stop(
    world: _World, linsight_endpoint, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(run_send, "stop_conversation_run", AsyncMock(side_effect=RuntimeError("redis down")))

    await linsight_endpoint._request_unified_stop(_version())

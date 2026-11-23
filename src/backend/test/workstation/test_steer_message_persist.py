"""F004 T042: a message sent while a run holds the conversation (AC-13, AC-14).

The message joins the inbox. At that moment its question row is written (same
structure as a normal question row; ``extra`` names the run that owns it and
carries the "queued" mark) and ``steer_accepted`` goes to the run's event
stream. When the run reads the message (``steer_read``) the mark is cleared, in
whichever process the run executes: the API process (direct run), the worker
(planned run, direct relay run).

The real router is driven through httpx. Redis is fakeredis; the message table
is the in-memory ``MessageTable``.
"""

from __future__ import annotations

import asyncio
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
from bisheng.linsight.domain.services.run_event_stream import EventWriter, RunEventStream
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.workstation.api.endpoints import chat as chat_endpoint
from bisheng.workstation.domain.services import chat_service, run_message_persist, run_send
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService
from bisheng.workstation.domain.services.run_lease import RunLeaseService
from test.workstation.run_persist_support import MessageTable

OWNER = 7
TENANT = 3
CID = "conv-steer-1"
PREFIX = "/api/v1/workstation"
V2 = {"X-BS-Run-Protocol": "2"}


def _handle(req, exc):
    if isinstance(exc, HTTPException):
        return ORJSONResponse(content={"status_code": exc.status_code, "status_message": exc.detail})
    return ORJSONResponse(content={"status_code": exc.code, "status_message": exc.message})


def _body(**over: Any) -> dict:
    return {"clientTimestamp": "2026-11-18T00:00:00Z", "conversationId": CID, "model": "m1", "text": "你好", **over}


class _World:
    def __init__(self, redis: Any, table: MessageTable):
        self.redis = redis
        self.table = table
        self.stream = RunEventStream(redis)
        self.lease = RunLeaseService(redis)
        self.dispatch = RunDispatchService(redis, enqueue_relay=AsyncMock())
        self.user = SimpleNamespace(user_id=OWNER, user_name="owner", tenant_id=TENANT)
        self.sessions: dict[str, Any] = {CID: SimpleNamespace(chat_id=CID, user_id=OWNER, name="已有会话")}
        self.started: list[Any] = []
        self.hooks: list[Any] = []
        self.gate = asyncio.Event()
        self.script: list[dict] = []
        self.tasks: list[asyncio.Task] = []

    async def events(self) -> list[dict]:
        return [event async for event in self.stream.read(CID, None)]

    def message(self, text: str, **over: Any) -> dict:
        return {"text": text, "task_mode": False, "user_id": OWNER, "tenant_id": TENANT, **over}


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    redis = fakeredis.aioredis.FakeRedis()
    w = _World(redis, MessageTable().install(monkeypatch))

    async def fake_redis():
        return redis

    monkeypatch.setattr(run_send, "_redis", fake_redis)
    monkeypatch.setattr(run_message_persist, "_redis", fake_redis)
    monkeypatch.setattr(run_send, "workbench_tenant_id", lambda user: user.tenant_id)
    monkeypatch.setattr(run_send, "_dispatch_wiring", lambda: {"enqueue_relay": w.dispatch._enqueue_relay})
    monkeypatch.setattr(run_send, "promote_chat_attachments", AsyncMock())
    monkeypatch.setattr(run_send, "register_session", AsyncMock())
    monkeypatch.setattr(chat_endpoint.MemoryGate, "open", AsyncMock())

    monkeypatch.setattr(
        run_send.SensitiveWordPolicyService, "evaluate_workbench_user_text", staticmethod(lambda *_a, **_k: None)
    )
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
    monkeypatch.setattr(chat_service, "_promote_generated_files", AsyncMock(return_value=[]))

    async def get_session(cid):
        return w.sessions.get(cid)

    async def open_conversation(data, login_user, session_subject=None):
        return w.sessions[data.conversationId], False

    async def model_name(data, login_user):
        return "模型一"

    monkeypatch.setattr(run_send, "_get_session", get_session)
    monkeypatch.setattr(run_send, "_open_conversation", open_conversation)
    monkeypatch.setattr(run_send, "_model_display_name", model_name)
    monkeypatch.setattr(run_send, "_spawn_title", lambda *a, **k: None)

    def start_direct_run(ctx, *, on_event=(), runner=None):
        """A direct run that waits at ``gate``, then plays ``script`` through the real hooks."""
        w.started.append(ctx)
        w.hooks = list(on_event)

        async def run():
            writer = EventWriter(w.stream, ctx.conversation_id, ctx.run_id)

            async def emit(event: dict) -> None:
                event = {**event, "run_id": ctx.run_id}
                await writer.emit(event)
                for hook in on_event:
                    await hook(event)

            await emit({"type": "run_started", "data": {"profile": "direct"}})
            await w.gate.wait()
            for event in [*w.script, {"type": "run_finished", "data": {}}]:
                await emit(event)
            await writer.aclose()
            await w.dispatch.on_run_finished(ctx.conversation_id, ctx.run_id)

        task = asyncio.create_task(run())
        w.tasks.append(task)
        return task

    monkeypatch.setattr(run_send, "start_direct_run", start_direct_run)

    yield w
    for task in w.tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*w.tasks, return_exceptions=True)
    await redis.aclose()


@pytest.fixture
async def client(world: _World):
    app = FastAPI()
    for exc_type in (HTTPException, BaseErrorCode):
        app.add_exception_handler(exc_type, _handle)
    app.include_router(chat_endpoint.router, prefix=PREFIX)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: world.user
    # The history endpoint also accepts a share link; none is presented here.
    app.dependency_overrides[header_share_token_parser] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _send(client: httpx.AsyncClient, text: str, **over: Any) -> dict:
    response = await client.post(f"{PREFIX}/chat/completions", json=_body(text=text, **over), headers=V2)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _history(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(f"{PREFIX}/messages/{CID}/agent")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ------------------------------------------------------------------ T042


async def test_steer_row_written_on_enqueue(world: _World, client: httpx.AsyncClient):
    first = await _send(client, "第一条")
    assert first["disposition"] == "started"

    files = [{"filepath": "a/b.txt", "file_name": "b.txt"}]
    second = await _send(client, "补充一句", files=files)

    assert second["disposition"] == "queued" and second["run_id"] == first["run_id"]
    normal, steer = world.table.questions()
    # Same structure as the question row of a normal turn.
    for column in ("user_id", "chat_id", "flow_id", "type", "is_bot", "sender", "category", "source"):
        assert getattr(steer, column) == getattr(normal, column), column
    assert json.loads(steer.message) == {"query": "补充一句", "files": files}
    assert json.loads(steer.files) == files
    assert steer.sensitive_status == normal.sensitive_status
    # ``extra`` names the owning run and carries the mark; a normal row has neither.
    assert world.table.extra(steer) == {
        "run_id": first["run_id"],
        "steer_message_id": second["message_id"],
        "queued": True,
    }
    assert world.table.extra(normal) == {}
    run_send.promote_chat_attachments.assert_awaited_with(files, OWNER)


async def test_steer_accepted_event(world: _World, client: httpx.AsyncClient):
    first = await _send(client, "第一条")
    await asyncio.sleep(0.01)  # the scripted run wrote run_started
    second = await _send(client, "补充一句")

    accepted = [e for e in await world.events() if e["type"] == "steer_accepted"]
    assert len(accepted) == 1
    assert accepted[0]["run_id"] == first["run_id"]
    assert accepted[0]["data"] == {"message_id": second["message_id"]}
    # The row exists by the time the event is on the stream.
    assert len(world.table.questions()) == 2


async def test_history_reflects_read_state(world: _World, client: httpx.AsyncClient):
    await _send(client, "第一条")
    second = await _send(client, "补充一句")

    row = (await _history(client))[-1]
    assert row["category"] == "question" and row["message"]["query"] == "补充一句"
    assert row["extra"]["queued"] is True
    assert row["extra"]["steer_message_id"] == second["message_id"]

    # The run reads the message: its hooks see ``steer_read`` (direct run, API process).
    world.script = [{"type": "steer_read", "data": {"message_id": second["message_id"]}}]
    world.gate.set()
    await asyncio.gather(*world.tasks)

    row = next(r for r in await _history(client) if r["message_id"] == row["message_id"])
    assert "queued" not in row["extra"]
    assert row["extra"]["steer_message_id"] == second["message_id"]
    # One UPDATE of one column, no read of the row.
    assert [(mid, set(fields)) for mid, fields in world.table.updates] == [(row["message_id"], {"extra"})]


# ------------------------------------------------------------ neighbours


async def test_normal_turn_row_has_no_mark_and_no_steer_event(world: _World, client: httpx.AsyncClient):
    await _send(client, "第一条")
    world.gate.set()
    await asyncio.gather(*world.tasks)

    assert [world.table.extra(r) for r in world.table.questions()] == [{}]
    assert not [e for e in await world.events() if e["type"].startswith("steer_")]


async def test_read_before_the_row_is_written_leaves_no_mark(world: _World):
    """The run may read the message between the inbox write and the row insert."""
    await run_message_persist.mark_steer_read(CID, "m-early", redis=world.redis)

    row = await world.table.ainsert_one(
        run_send._question_row(
            SimpleNamespace(text="补充", files=None),
            world.user,
            CID,
            run_message_persist.steer_extra("run-1", "m-early", queued=True),
        )
    )
    still_queued = await run_message_persist.bind_steer_row(world.redis, CID, "m-early", row.id, "run-1")

    assert still_queued is False
    assert world.table.extra(row) == {"run_id": "run-1", "steer_message_id": "m-early"}


async def test_second_steer_read_is_a_no_op(world: _World, client: httpx.AsyncClient):
    await _send(client, "第一条")
    second = await _send(client, "补充一句")

    hook = run_message_persist.steer_read_hook(CID, redis=world.redis)
    event = {"type": "steer_read", "data": {"message_id": second["message_id"]}}
    await hook(event)
    await hook(event)
    await hook({"type": "text", "data": {"text": "无关"}})

    assert len(world.table.updates) == 1


async def test_row_failure_keeps_the_message_and_the_event(world: _World, client: httpx.AsyncClient, monkeypatch):
    """The message is already in the inbox: a failed row insert must not answer the send with an error."""
    first = await _send(client, "第一条")
    monkeypatch.setattr(run_send, "_insert_steer_row", AsyncMock(side_effect=RuntimeError("db down")))

    second = await _send(client, "补充一句")

    assert second["disposition"] == "queued"
    assert await world.dispatch.inbox_length(CID) == 1
    accepted = [e for e in await world.events() if e["type"] == "steer_accepted"]
    assert [e["data"]["message_id"] for e in accepted] == [second["message_id"]]
    assert first["run_id"] == accepted[0]["run_id"]


async def test_planned_run_sink_clears_the_mark(world: _World, client: httpx.AsyncClient, monkeypatch):
    """A planned run executes in the worker: its sink (``_UnifiedRun.emit``) clears the mark there."""
    from bisheng.linsight.domain import task_exec

    await _send(client, "第一条")
    second = await _send(client, "补充一句")
    state = await world.lease.get_state(CID)

    run = task_exec._UnifiedRun(
        conversation_id=CID,
        run_id=state.run_id,
        session_version_id="svid-1",
        redis=world.redis,
        lease=world.lease,
        dispatch=world.dispatch,
        stream=world.stream,
    )
    await run.emit({"type": "steer_read", "data": {"message_id": second["message_id"]}, "run_id": state.run_id})
    await run.writer.aclose()

    steer = world.table.questions()[-1]
    assert "queued" not in world.table.extra(steer)
    assert [e["type"] for e in await world.events()][-1] == "steer_read"


async def test_planned_sink_survives_a_failing_update(world: _World, monkeypatch):
    from bisheng.linsight.domain import task_exec

    monkeypatch.setattr(run_message_persist, "mark_steer_read", AsyncMock(side_effect=RuntimeError("db down")))
    run = task_exec._UnifiedRun(
        conversation_id=CID,
        run_id="run-x",
        session_version_id="svid-1",
        redis=world.redis,
        lease=world.lease,
        dispatch=world.dispatch,
        stream=world.stream,
    )
    await world.stream.append(CID, {"type": "run_started", "run_id": "run-x", "data": {}})

    await run.emit({"type": "steer_read", "data": {"message_id": "m1"}, "run_id": "run-x"})
    await run.writer.aclose()

    assert [e["type"] for e in await world.events()] == ["run_started", "steer_read"]

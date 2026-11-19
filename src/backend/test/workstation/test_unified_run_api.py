"""F004 T031: the subscribe endpoint and the send endpoint on the unified path.

Covers AC-01 (one entry for both modes), AC-06 (deep research needs its menu
permission on the server), AC-28 / owner-only access to a conversation's
events, AC-31 (a reconnect continues from its cursor) and AC-38 (input safety
runs before a message can reach the inbox).

The real router is mounted on a minimal FastAPI app and driven through httpx in
the test's own event loop. Redis is fakeredis (Lua enabled). The database is
replaced by in-memory fakes at the helper boundary of ``run_send``. No agent
runs here: ``start_direct_run`` is replaced by a scripted run that writes
unified events to the real event stream and calls the real persistence
projector (the executor itself is covered by test_direct_run.py).
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
from fastapi.responses import ORJSONResponse, StreamingResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.linsight.domain.services.run_event_stream import EventWriter, RunEventStream
from bisheng.workstation.api.endpoints import chat as chat_endpoint
from bisheng.workstation.domain.services import chat_service, run_send
from bisheng.workstation.domain.services.run_dispatch import RunDispatchService, inbox_key
from bisheng.workstation.domain.services.run_lease import RunLeaseService

OWNER = 7
TENANT = 3
CID = "conv-api-1"
PREFIX = "/api/v1/workstation"
V2 = {"X-BS-Run-Protocol": "2"}


def _handle(req, exc):
    if isinstance(exc, HTTPException):
        return ORJSONResponse(content={"status_code": exc.status_code, "status_message": exc.detail})
    return ORJSONResponse(content={"status_code": exc.code, "status_message": exc.message})


def _body(**over: Any) -> dict:
    return {"clientTimestamp": "2026-11-18T00:00:00Z", "conversationId": CID, "model": "m1", "text": "你好", **over}


def _frames(text: str) -> list[dict]:
    """Parse an SSE body into ``{"event", "id", "data"}`` records (comments dropped)."""
    out = []
    for block in text.split("\n\n"):
        record: dict[str, Any] = {}
        for line in block.split("\n"):
            if line.startswith(":") or ":" not in line:
                continue
            key, _, value = line.partition(": ")
            record[key] = json.loads(value) if key == "data" else value
        if record:
            out.append(record)
    return out


class _World:
    """Everything one test can inspect."""

    def __init__(self, redis: Any):
        self.redis = redis
        self.stream = RunEventStream(redis)
        self.lease = RunLeaseService(redis)
        self.dispatch = RunDispatchService(redis, enqueue_relay=AsyncMock())
        self.user = SimpleNamespace(user_id=OWNER, user_name="owner", tenant_id=TENANT)
        self.flag = True
        self.sessions: dict[str, Any] = {CID: SimpleNamespace(chat_id=CID, user_id=OWNER, name="已有会话")}
        self.question_rows: list[dict] = []
        self.answer_rows: list[Any] = []
        self.started: list[Any] = []
        self.script: list[dict] = []
        self.tasks: list[asyncio.Task] = []
        self.task_turns: list[Any] = []

    async def state(self, cid: str = CID):
        return await self.lease.get_state(cid)

    async def inbox(self, cid: str = CID) -> int:
        return int(await self.redis.llen(inbox_key(cid)))


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    redis = fakeredis.aioredis.FakeRedis()
    w = _World(redis)

    async def fake_redis():
        return redis

    monkeypatch.setattr(run_send, "_redis", fake_redis)
    # The request middleware sets the tenant ContextVar in production. Here no
    # middleware runs, and a value another test module left behind would win.
    monkeypatch.setattr(run_send, "workbench_tenant_id", lambda user: user.tenant_id)
    monkeypatch.setattr(run_send, "_dispatch_wiring", lambda: {"enqueue_relay": w.dispatch._enqueue_relay})
    monkeypatch.setattr(run_send, "FOLLOW_BLOCK_MS", 20)
    monkeypatch.setattr(run_send, "PERSIST_WAIT_SECONDS", 2)

    async def flag(_login_user, _subject):
        return w.flag

    monkeypatch.setattr(chat_service, "_unified_runtime_on", flag)
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", staticmethod(lambda *_a, **_k: None)
    )

    # -- database fakes at the helper boundary of run_send ---------------------
    async def get_session(cid):
        return w.sessions.get(cid)

    async def open_conversation(data, login_user):
        cid = data.conversationId
        is_new = not cid
        if is_new:
            cid = f"new-{len(w.sessions)}"
            w.sessions[cid] = SimpleNamespace(chat_id=cid, user_id=login_user.user_id, name="New Chat")
        session = w.sessions.get(cid)
        if session is None or session.user_id != login_user.user_id:
            raise run_send.ConversationNotFoundError()
        return session, is_new

    async def insert_question(data, login_user, cid, memory_register):
        row = SimpleNamespace(id=100 + len(w.question_rows), chat_id=cid)
        w.question_rows.append({"id": row.id, "chat_id": cid, "text": data.text})
        return row

    async def model_name(data, login_user):
        return "模型一"

    monkeypatch.setattr(run_send, "_get_session", get_session)
    monkeypatch.setattr(run_send, "_open_conversation", open_conversation)
    monkeypatch.setattr(run_send, "_insert_question_row", insert_question)
    monkeypatch.setattr(run_send, "_model_display_name", model_name)
    monkeypatch.setattr(run_send, "_spawn_title", lambda *a, **k: None)
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", AsyncMock(return_value=None))

    # -- the answer row is written by the REAL projector through these ----------
    async def insert_answer(row):
        row.id = 500 + len(w.answer_rows)
        w.answer_rows.append(row)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", insert_answer)
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock())
    monkeypatch.setattr(chat_service, "_promote_generated_files", AsyncMock(return_value=[]))

    # -- scripted direct run -------------------------------------------------------
    def start_direct_run(ctx, *, on_event=(), runner=None):
        w.started.append(ctx)
        script = list(w.script)

        async def run():
            writer = EventWriter(w.stream, ctx.conversation_id, ctx.run_id)
            parked = False
            for event in [{"type": "run_started", "data": {"profile": "direct"}}, *script]:
                event = {**event, "run_id": ctx.run_id}
                await writer.emit(event)
                for hook in on_event:
                    await hook(event)
                parked = event["type"] == "ask_user"
                await asyncio.sleep(0)
            await writer.aclose()
            if parked:
                await w.lease.park(ctx.conversation_id, ctx.run_id)
            else:
                await w.dispatch.on_run_finished(ctx.conversation_id, ctx.run_id)

        task = asyncio.create_task(run())
        w.tasks.append(task)
        return task

    monkeypatch.setattr(run_send, "start_direct_run", start_direct_run)

    # -- planned hand-over -----------------------------------------------------
    async def submit_task_turn(data, login_user, **kwargs):
        w.task_turns.append(data)
        return (
            SimpleNamespace(chat_id=data.conversationId, name="已有会话"),
            SimpleNamespace(id="svid-1", session_id=data.conversationId),
        )

    monkeypatch.setattr(run_send, "_submit_task_turn", submit_task_turn)

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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _finished_run(world: _World, run_id: str = "run-old") -> list[str]:
    ids = []
    for event in (
        {"type": "run_started", "data": {}},
        {"type": "text", "data": {"text": "第一段"}},
        {"type": "text", "data": {"text": "第二段"}},
        {"type": "run_finished", "data": {}},
    ):
        ids.append(await world.stream.append(CID, {**event, "run_id": run_id}))
    return ids


# --------------------------------------------------------------- subscribe


async def test_subscribe_owner_only(world: _World, client: httpx.AsyncClient):
    await _finished_run(world)

    mine = await client.get(f"{PREFIX}/conversations/{CID}/events")
    assert mine.status_code == 200
    assert mine.headers["content-type"].startswith("text/event-stream")
    events = _frames(mine.text)
    assert [e["data"]["type"] for e in events] == ["run_started", "text", "text", "run_finished"]
    assert all(e["id"] == e["data"]["id"] for e in events)
    assert {"id", "run_id", "seq", "type", "data", "ts"} <= set(events[0]["data"])

    world.user = SimpleNamespace(user_id=OWNER + 1, user_name="other", tenant_id=TENANT)
    other = await client.get(f"{PREFIX}/conversations/{CID}/events")
    assert not other.headers["content-type"].startswith("text/event-stream")
    assert other.json()["status_code"] == UnAuthorizedError.Code
    assert "第一段" not in other.text

    missing = await client.get(f"{PREFIX}/conversations/does-not-exist/events")
    assert missing.json()["status_code"] == UnAuthorizedError.Code


async def test_subscribe_resume_from_cursor(world: _World, client: httpx.AsyncClient):
    ids = await _finished_run(world)

    resp = await client.get(f"{PREFIX}/conversations/{CID}/events", headers={"Last-Event-ID": ids[1]})

    events = _frames(resp.text)
    assert [e["id"] for e in events] == ids[2:]
    assert [e["data"]["type"] for e in events] == ["text", "run_finished"]


async def test_subscribe_waits_for_first_event(world: _World, client: httpx.AsyncClient):
    """A subscriber that connects before the run wrote anything still gets the run."""
    await _finished_run(world, "run-old")
    result = await world.dispatch.submit(CID, {"text": "hi", "user_id": OWNER, "tenant_id": TENANT})
    old_last = (await world.stream.snapshot(CID))["last_id"]

    async def late_run():
        await asyncio.sleep(0.1)
        for event in (
            {"type": "run_started", "data": {}},
            {"type": "text", "data": {"text": "新回答"}},
            {"type": "run_finished", "data": {}},
        ):
            await world.stream.append(CID, {**event, "run_id": result.run_id})
        await world.dispatch.on_run_finished(CID, result.run_id)

    world.tasks.append(asyncio.create_task(late_run()))
    resp = await asyncio.wait_for(
        client.get(f"{PREFIX}/conversations/{CID}/events", headers={"Last-Event-ID": old_last}), timeout=5
    )

    events = _frames(resp.text)
    assert [e["data"]["type"] for e in events] == ["run_started", "text", "run_finished"]
    assert {e["data"]["run_id"] for e in events} == {result.run_id}


# -------------------------------------------------------------------- send


async def test_send_negotiated_json(world: _World, client: httpx.AsyncClient):
    gate = asyncio.Event()
    world.script = []
    real_start = run_send.start_direct_run

    def held_start(ctx, **kwargs):
        # The run stays "running" until the test lets it go.
        world.started.append(ctx)
        task = asyncio.create_task(gate.wait())
        world.tasks.append(task)
        return task

    run_send.start_direct_run = held_start
    try:
        first = await client.post(f"{PREFIX}/chat/completions", json=_body(text="第一条"), headers=V2)
        second = await client.post(f"{PREFIX}/chat/completions", json=_body(text="第二条"), headers=V2)
    finally:
        run_send.start_direct_run = real_start
        gate.set()

    assert first.headers["content-type"].startswith("application/json")
    data = first.json()["data"]
    assert set(data) >= {"run_id", "disposition", "message_id"}
    assert data["disposition"] == "started"
    assert data["conversation_id"] == CID
    state = await world.state()
    assert (state.status, state.run_id, state.profile) == ("running", data["run_id"], "direct")

    assert len(world.started) == 1
    ctx = world.started[0]
    assert (ctx.conversation_id, ctx.run_id, ctx.text) == (CID, data["run_id"], "第一条")
    assert (ctx.tenant_id, ctx.user_id, ctx.model_id) == (TENANT, OWNER, "m1")
    assert [row["text"] for row in world.question_rows] == ["第一条"]

    queued = second.json()["data"]
    assert queued["disposition"] == "queued"
    assert queued["run_id"] == data["run_id"]
    assert queued["message_id"] != data["message_id"]
    assert await world.inbox() == 1
    assert len(world.started) == 1


async def test_send_new_conversation_returns_its_id(world: _World, client: httpx.AsyncClient):
    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(conversationId=None), headers=V2)

    data = resp.json()["data"]
    assert data["disposition"] == "started"
    assert data["conversation_id"] in world.sessions and data["conversation_id"] != CID
    assert world.started[0].conversation_id == data["conversation_id"]


async def test_send_legacy_stream_shape(world: _World, client: httpx.AsyncClient):
    world.script = [
        {"type": "thinking", "data": {"text": "先想一下", "call_id": "t1"}},
        {"type": "text", "data": {"text": "我去查"}},
        {
            "type": "tool_call",
            "data": {"call_id": "c1", "name": "web_search", "status": "start", "params": {"query": "天气"}},
        },
        {
            "type": "tool_call",
            "data": {"call_id": "c1", "name": "web_search", "status": "end", "output": "晴"},
        },
        {"type": "plan", "data": {"items": []}},
        {"type": "text", "data": {"text": "，今天晴。"}},
        {"type": "run_finished", "data": {}},
    ]

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(text="天气如何"))

    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = _frames(resp.text)
    datas = [f["data"] for f in frames]
    assert all(f.get("event", "message") == "message" for f in frames)

    question_id = world.question_rows[0]["id"]
    assert datas[0] == {
        "message": {"messageId": question_id, "conversationId": CID, "sender": "User", "text": "天气如何"},
        "created": True,
    }
    shape = [(d.get("category"), d.get("type")) for d in datas[1:-1]]
    assert shape == [
        ("processing", "begin"),
        ("question", "over"),
        ("agent_thinking", "stream"),
        ("agent_thinking", "end"),
        ("agent_answer", "stream"),
        ("agent_tool_call", "start"),
        ("agent_tool_call", "end"),
        ("agent_answer", "stream"),
        ("agent_answer", "end"),
        ("processing", "close"),
    ]
    by = {s: d for s, d in zip(shape, datas[1:-1], strict=True)}
    assert by[("question", "over")]["message"] == {"query": "天气如何", "files": []}
    assert by[("question", "over")]["message_id"] == question_id and by[("question", "over")]["is_bot"] is False
    assert by[("agent_thinking", "stream")]["message"] == {"content": "先想一下"}
    assert "duration_ms" in by[("agent_thinking", "end")]["message"]
    assert datas[5]["message"] == {"msg": "我去查"}
    start = by[("agent_tool_call", "start")]["message"]
    assert start["tool_call_id"] == "c1" and start["tool_name"] == "web_search" and start["args"] == {"query": "天气"}
    end = by[("agent_tool_call", "end")]["message"]
    assert end["tool_call_id"] == "c1" and end["error"] is None and "duration_ms" in end
    assert {"category", "type", "message", "is_bot", "chat_id", "flow_id"} <= set(datas[1])
    assert all(d["chat_id"] == CID for d in datas[1:-1])

    # The terminal frames carry the row the projector saved.
    assert len(world.answer_rows) == 1
    row = world.answer_rows[0]
    answer_end = by[("agent_answer", "end")]
    assert answer_end["message_id"] == row.id
    assert answer_end["message"]["msg"] == "我去查，今天晴。"
    assert answer_end["message"]["events"] == json.loads(row.message)["events"]
    assert answer_end["message"]["files"] == []
    assert datas[-1] == {
        "final": True,
        "conversation": {"conversationId": CID},
        "responseMessage": {"messageId": row.id, "conversationId": CID},
    }
    assert (await world.state()).status == "idle"


async def test_send_legacy_stream_reports_failure(world: _World, client: httpx.AsyncClient):
    world.script = [
        {"type": "text", "data": {"text": "半句"}},
        {"type": "run_failed", "data": {"code": 500, "reason": "chat_unknown", "detail": "boom", "reference_id": "r"}},
    ]

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body())

    frames = _frames(resp.text)
    errors = [f for f in frames if f.get("event") == "error"]
    assert len(errors) == 1 and errors[0]["data"]["status_message"] == "boom"
    tail = [(f["data"].get("category"), f["data"].get("type")) for f in frames[-3:-1]]
    assert tail == [("agent_answer", "end"), ("processing", "close")]
    assert frames[-1]["data"]["final"] is True
    assert frames.index(errors[0]) < len(frames) - 3


async def test_task_mode_requires_permission(world: _World, client: httpx.AsyncClient, monkeypatch):
    check = AsyncMock(side_effect=UnAuthorizedError.http_exception())
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", check)

    for headers in (V2, {}):
        resp = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=True), headers=headers)
        assert resp.json()["status_code"] == UnAuthorizedError.Code
    check.assert_awaited_with(OWNER, "linsight_task_mode")
    assert (await world.state()).status == "idle"
    assert await world.inbox() == 0
    assert world.task_turns == [] and world.started == [] and world.question_rows == []

    # A direct answer of the same user is not affected (AC-06).
    ok = await client.post(f"{PREFIX}/chat/completions", json=_body(), headers=V2)
    assert ok.json()["data"]["disposition"] == "started"


async def test_task_mode_hands_over_to_the_worker_queue(world: _World, client: httpx.AsyncClient):
    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=True), headers=V2)

    data = resp.json()["data"]
    assert data["disposition"] == "started"
    assert len(world.task_turns) == 1 and world.task_turns[0].conversationId == CID
    assert world.started == []
    state = await world.state()
    assert (state.status, state.run_id, state.profile) == ("running", data["run_id"], "planned")

    # A daily message sent while deep research runs joins the inbox (AC-01: per message).
    again = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=False), headers=V2)
    assert again.json()["data"]["disposition"] == "queued"
    assert world.started == []


async def test_task_mode_legacy_client_gets_the_handoff_frame(world: _World, client: httpx.AsyncClient):
    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=True))

    frames = _frames(resp.text)
    assert [f["data"] for f in frames] == [
        {"event": "linsight_task_handoff", "data": {"session_version_id": "svid-1", "chat_id": CID}}
    ]


async def test_flag_off_uses_legacy_path(world: _World, client: httpx.AsyncClient, monkeypatch):
    world.flag = False
    seen: list[tuple[str, Any]] = []

    def legacy(name):
        async def handler(request, data, login_user, *args, **kwargs):
            seen.append((name, data))
            return StreamingResponse(
                iter([f"data: {json.dumps({'legacy': name})}\n\n"]), media_type="text/event-stream"
            )

        return handler

    monkeypatch.setattr(chat_service, "_agent_stream_chat_completion", legacy("daily"))
    monkeypatch.setattr(chat_service, "_task_mode_stream_completion", legacy("task"))
    monkeypatch.setattr(
        chat_service.DepartmentFlowService,
        "hold_execution_lease",
        lambda _user: _Held(),
    )
    unified = AsyncMock()
    monkeypatch.setattr(run_send, "unified_send", unified)

    daily = await client.post(f"{PREFIX}/chat/completions", json=_body(), headers=V2)
    task = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=True))

    assert _frames(daily.text)[0]["data"] == {"legacy": "daily"}
    assert _frames(task.text)[0]["data"] == {"legacy": "task"}
    assert [name for name, _ in seen] == ["daily", "task"]
    assert seen[0][1].skills == []
    unified.assert_not_awaited()
    assert (await world.state()).status == "idle"
    assert world.started == [] and world.task_turns == []


class _Held:
    async def __aenter__(self):
        from bisheng.department.domain.services.department_flow_service import SlotOutcome

        return SlotOutcome.HELD, None

    async def __aexit__(self, *exc):
        return False


async def test_sensitive_input_blocked_before_inbox(world: _World, client: httpx.AsyncClient, monkeypatch):
    # A run holds the conversation, so an accepted message would join the inbox.
    held = await world.dispatch.submit(CID, {"text": "先问一句", "user_id": OWNER, "tenant_id": TENANT})
    hit = SimpleNamespace(auto_reply="内容不合规")
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", staticmethod(lambda *_a, **_k: hit)
    )
    blocked_calls: list[Any] = []

    async def blocked_response(data, login_user, blocked, memory_register, negotiated=False):
        blocked_calls.append(blocked)
        return StreamingResponse(iter(['data: {"blocked": true}\n\n']), media_type="text/event-stream")

    monkeypatch.setattr(run_send, "_blocked_response", blocked_response)

    for body in (_body(text="敏感词"), _body(text="敏感词", task_mode=True)):
        resp = await client.post(f"{PREFIX}/chat/completions", json=body, headers=V2)
        assert _frames(resp.text) == [{"data": {"blocked": True}}]

    assert blocked_calls == [hit, hit]
    assert await world.inbox() == 0
    state = await world.state()
    assert (state.status, state.run_id) == ("running", held.run_id)
    assert world.started == [] and world.task_turns == [] and world.question_rows == []


# ------------------------------------- design §7 item 3: blocked input on the run protocol


def _block_input(world: _World, monkeypatch, auto_reply: str = "内容不合规") -> dict[str, Any]:
    """Input content safety hits; the blocked turn is recorded through today's helpers."""
    seen: dict[str, Any] = {"init": [], "answers": [], "legacy": []}
    hit = SimpleNamespace(auto_reply=auto_reply)
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", staticmethod(lambda *_a, **_k: hit)
    )

    async def initialize(data, login_user, session_subject=None, *, skip_llm=False, memory_register=None):
        seen["init"].append({"text": data.text, "skip_llm": skip_llm})
        conversation = world.sessions[data.conversationId]
        return None, conversation, SimpleNamespace(id=901), None, SimpleNamespace(displayName="模型一"), False

    async def persist_answer(conversation, model_info, reply):
        seen["answers"].append((conversation.chat_id, model_info.displayName, reply))
        return SimpleNamespace(id=902)

    def legacy_frames(conversation, message, model_info, data, reply):
        seen["legacy"].append(reply)
        return StreamingResponse(iter(['data: {"blocked": true}\n\n']), media_type="text/event-stream")

    monkeypatch.setattr(chat_service, "_agent_initialize_chat", initialize)
    monkeypatch.setattr(chat_service, "persist_blocked_workbench_answer", persist_answer)
    monkeypatch.setattr(chat_service, "_respond_blocked_workbench", legacy_frames)
    return seen


async def test_blocked_input_answers_in_the_run_protocol(world: _World, client: httpx.AsyncClient, monkeypatch):
    seen = _block_input(world, monkeypatch)

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(text="敏感词"), headers=V2)

    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["status_code"] == 200
    assert body["data"] == {
        "run_id": None,
        "disposition": "blocked",
        "message_id": None,
        "conversation_id": CID,
        "content_safety": True,
        "auto_reply": "内容不合规",
        "question_message_id": 901,
        "answer_message_id": 902,
    }
    # The turn is recorded exactly once, with the auto-reply, and no model is built.
    assert seen["init"] == [{"text": "敏感词", "skip_llm": True}]
    assert seen["answers"] == [(CID, "模型一", "内容不合规")]
    assert seen["legacy"] == []
    # No run, nothing in the inbox, nothing on the event stream.
    assert world.started == [] and world.task_turns == []
    assert (await world.state()).status == "idle"
    assert await world.inbox() == 0
    assert [event async for event in world.stream.read(CID)] == []


async def test_blocked_input_during_a_run_does_not_touch_the_run(world: _World, client: httpx.AsyncClient, monkeypatch):
    held = await world.dispatch.submit(CID, {"text": "先问一句", "user_id": OWNER, "tenant_id": TENANT})
    await world.stream.append(CID, {"type": "run_started", "run_id": held.run_id, "data": {}})
    _block_input(world, monkeypatch)

    for body in (_body(text="敏感词"), _body(text="敏感词", task_mode=True)):
        resp = await client.post(f"{PREFIX}/chat/completions", json=body, headers=V2)
        assert resp.json()["data"]["disposition"] == "blocked"

    # The blocked text never joined the inbox, and the stream of the live run is untouched.
    assert await world.inbox() == 0
    state = await world.state()
    assert (state.status, state.run_id) == ("running", held.run_id)
    assert [event["type"] async for event in world.stream.read(CID)] == ["run_started"]


async def test_blocked_input_without_the_header_keeps_the_old_frames(
    world: _World, client: httpx.AsyncClient, monkeypatch
):
    seen = _block_input(world, monkeypatch)

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(text="敏感词"))

    assert _frames(resp.text) == [{"data": {"blocked": True}}]
    assert seen["legacy"] == ["内容不合规"]
    # The SSE helper writes the answer row itself.
    assert seen["answers"] == []


# ------------------------------------------------- review M1 / M3 / M4


async def test_task_mode_send_that_cannot_be_queued_frees_the_conversation(
    world: _World, client: httpx.AsyncClient, monkeypatch
):
    """M1: a planned run holds the 4-hour queued lease before it is queued."""
    from bisheng.common.errcode.linsight import LinsightStartTaskError

    async def queue_down(data, login_user, **kwargs):
        raise LinsightStartTaskError()

    monkeypatch.setattr(run_send, "_submit_task_turn", queue_down)

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(task_mode=True), headers=V2)

    assert resp.json()["status_code"] == LinsightStartTaskError.Code
    state = await world.state()
    assert state.status == "idle" and state.run_id is None
    # The next message starts a run instead of joining the inbox of a run that does not exist.
    again = await client.post(f"{PREFIX}/chat/completions", json=_body(), headers=V2)
    assert again.json()["data"]["disposition"] == "started"


class _ResumeQueue:
    items: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def put_head(self, item):
        _ResumeQueue.items.append(item)


def _versions(monkeypatch, versions: list) -> None:
    """Run records of the conversation, newest first, as the DAO returns them."""
    import bisheng.linsight.worker as worker_mod
    from bisheng.core.cache import redis_manager
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao

    async def get_by_id(version_id):
        return next((v for v in versions if v.id == version_id), None)

    async def by_session(session_id):
        return [v for v in versions if v.session_id == session_id]

    monkeypatch.setattr(LinsightSessionVersionDao, "get_by_id", staticmethod(get_by_id))
    monkeypatch.setattr(LinsightSessionVersionDao, "get_session_versions_by_session_id", staticmethod(by_session))
    _ResumeQueue.items = []
    monkeypatch.setattr(worker_mod, "LinsightQueue", _ResumeQueue)
    monkeypatch.setattr(redis_manager, "get_redis_client", AsyncMock(return_value=object()))


def _version(version_id: str, run_id: str | None = None, status: Any = None) -> Any:
    return SimpleNamespace(
        id=version_id, session_id=CID, api_meta={"run_id": run_id} if run_id else None, status=status, model="m1"
    )


async def _park_planned(world: _World) -> str:
    result = await world.dispatch.submit(
        CID, {"text": "研究一下", "task_mode": True, "user_id": OWNER, "tenant_id": TENANT}
    )
    assert await world.lease.park(CID, result.run_id)
    return result.run_id


async def test_answer_resumes_the_parked_run_not_the_newest_record(
    world: _World, client: httpx.AsyncClient, monkeypatch
):
    """M3: another entry added a newer record while the run waited for its answer."""
    run_id = await _park_planned(world)
    _versions(monkeypatch, [_version("sv-newer-of-another-entry"), _version("sv-parked", run_id)])

    resp = await client.post(f"{PREFIX}/chat/completions", json=_body(text="第一种"), headers=V2)

    assert resp.json()["data"]["run_id"] == run_id
    assert [item["session_version_id"] for item in _ResumeQueue.items] == ["sv-parked"]
    assert _ResumeQueue.items[0]["resume"] is True and _ResumeQueue.items[0]["user_input"] == "第一种"


async def test_answer_to_a_run_without_a_record_fails_and_keeps_the_question_open(
    world: _World, client: httpx.AsyncClient, monkeypatch
):
    """M3: no fallback to the newest record; the run waits for the answer again."""
    run_id = await _park_planned(world)
    _versions(monkeypatch, [_version("sv-newer-of-another-entry")])

    with pytest.raises(RuntimeError, match="has no run record"):
        await client.post(f"{PREFIX}/chat/completions", json=_body(text="第一种"), headers=V2)

    assert _ResumeQueue.items == []
    state = await world.state()
    assert (state.status, state.run_id) == ("waiting", run_id)


async def test_stop_never_takes_the_newest_record_for_the_queued_run(world: _World, monkeypatch):
    """M3 (same class): the record of the run is found by its run id or not at all."""
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum

    other = _version("sv-newer-of-another-entry", status=SessionVersionStatusEnum.NOT_STARTED)
    mine = _version("sv-queued", "run-queued", status=SessionVersionStatusEnum.NOT_STARTED)
    _versions(monkeypatch, [other, mine])

    assert (await run_send._planned_run_record(CID, "run-queued")).id == "sv-queued"
    assert await run_send._planned_run_record(CID, "run-without-record") is None


async def test_follower_backs_off_while_a_held_conversation_has_no_stream(world: _World, monkeypatch):
    """M4: a parked (or queued) run without a Stream must not be polled every 50 ms."""
    await _park_planned(world)
    assert not await world.redis.exists(f"bisheng:run:events:{{{CID}}}")
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(run_send.asyncio, "sleep", record_sleep)
    svc = await run_send.run_services()
    beats = 0
    async for event in run_send.follow_run_events(svc, CID):
        assert event == {"type": "heartbeat"}
        beats += 1
        if beats == 8:
            break

    assert sleeps[:7] == [0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0]

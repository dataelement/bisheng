"""Mobile access keeps the desktop and phone contracts while crossing workers."""

import asyncio
import contextlib
import json
import time
from types import SimpleNamespace

import anyio
import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
from redis.exceptions import RedisError
from starlette.websockets import WebSocketDisconnect

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.api.endpoints.mobile import MobileStreamingResponse, mobile_service, router
from bisheng.dsh.api.router import router as dsh_router
from bisheng.dsh.domain.services.mobile_access import MobileAccessService, MobileResult, MobileStream
from bisheng.dsh.infrastructure.mobile_access import MobileAccessStore

DESKTOP_ID = "a" * 43
SECRET = "b" * 43
OTHER_SECRET = "c" * 43


class FakeSocket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        await self.sent.put(data)

    async def receive_json(self):
        item = await self.incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    async def close(self):
        self.closed = True
        await self.incoming.put(None)


def user(user_id=7, tenant_id=3):
    return SimpleNamespace(user_id=user_id, tenant_id=tenant_id)


def service_pair(**kwargs):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis)
    return MobileAccessService(store, **kwargs), MobileAccessService(store, **kwargs), store


async def bind(service, owner=None, desktop_id=DESKTOP_ID, secret=SECRET, display_name="Office"):
    return await service.bind(
        owner or user(),
        {"desktopId": desktop_id, "attachSecret": secret, "displayName": display_name},
    )


async def connect(service, secret=SECRET, desktop_id=DESKTOP_ID, client_ip="127.0.0.1"):
    socket = FakeSocket()
    task = asyncio.create_task(service.attach(socket, client_ip))
    await socket.incoming.put({"type": "attach", "desktopId": desktop_id, "attachSecret": secret})
    return socket, task


async def wait_online(store, desktop_id=DESKTOP_ID):
    for _ in range(50):
        if await store.current_connection(desktop_id):
            return await store.current_connection(desktop_id)
        await asyncio.sleep(0.02)
    raise AssertionError("desktop did not come online")


async def stop(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _dependency_calls(route):
    return [dependency.call for dependency in route.dependant.dependencies]


def test_routes_are_mounted_without_dsh_route_class():
    paths = {route.path for route in dsh_router.routes}
    assert "/dsh/mobile/bind" in paths
    assert "/dsh/mobile/attach" in paths
    mobile = next(route for route in dsh_router.routes if route.path == "/dsh/mobile/bind")
    assert type(mobile).__name__ == "APIRoute"


def test_registration_uses_desktop_credential_and_listing_uses_website_login():
    by_path = {route.path: route for route in router.routes}
    for path in ("/dsh/mobile/bind", "/dsh/mobile/unbind"):
        calls = _dependency_calls(by_path[path])
        assert desktop_principal in calls
        assert UserPayload.get_login_user not in calls
    for path in (
        "/dsh/mobile/desktops",
        "/dsh/mobile/desktops/{desktop_id}/rpc",
        "/dsh/mobile/desktops/{desktop_id}/session/stream",
    ):
        calls = _dependency_calls(by_path[path])
        assert UserPayload.get_login_user in calls
        assert desktop_principal not in calls


def test_http_contract_uses_bare_responses():
    holder, _, _ = service_pair()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[mobile_service] = lambda: holder

    async def current_user():
        return user()

    async def current_desktop():
        return SimpleNamespace(user_id="7", tenant_id="3")

    app.dependency_overrides[UserPayload.get_login_user] = current_user
    app.dependency_overrides[desktop_principal] = current_desktop
    with TestClient(app) as client:
        assert client.post("/api/v1/dsh/mobile/bind", json=[]).status_code == 400
        assert client.post("/api/v1/dsh/mobile/bind", json={"desktopId": 12, "attachSecret": SECRET}).status_code == 400
        bound = client.post(
            "/api/v1/dsh/mobile/bind",
            json={"desktopId": DESKTOP_ID, "attachSecret": SECRET, "displayName": "Office"},
        )
        assert bound.status_code == 200
        listed = client.get("/api/v1/dsh/mobile/desktops")
        assert listed.status_code == 200
        assert listed.json() == {"desktops": [{"desktopId": DESKTOP_ID, "displayName": "Office", "online": False}]}
        missing = client.post(f"/api/v1/dsh/mobile/desktops/{DESKTOP_ID}/rpc", json={"method": "session.list"})
        assert missing.status_code == 503
        assert missing.json() == {"error": "offline"}


@pytest.mark.asyncio
async def test_registration_is_scoped_and_uses_desktop_hash_tag():
    holder, _, store = service_pair()
    owner = user()
    other = user(8, 4)
    assert (await bind(holder, owner)).status == 200
    assert (await bind(holder, other, secret=OTHER_SECRET)).status == 409
    visible = await holder.list_desktops(owner)
    hidden = await holder.list_desktops(other)
    assert visible.body["desktops"][0]["desktopId"] == DESKTOP_ID
    assert hidden.body["desktops"] == []
    assert (await holder.rpc(other, DESKTOP_ID, {"method": "session.list", "payload": {}})).status == 404
    registration_key = store.registration_key(DESKTOP_ID)
    assert f"{{{DESKTOP_ID}}}" in registration_key
    assert f"{{{DESKTOP_ID}}}" in store.online_key(DESKTOP_ID)
    assert f"{{{DESKTOP_ID}}}" in store.request_key(DESKTOP_ID, "connection")
    stored = await store.read(DESKTOP_ID)
    assert stored is not None
    assert SECRET not in stored.secret_hash
    await store.redis.delete(store.online_key(DESKTOP_ID))
    listed = await holder.list_desktops(owner)
    assert listed.body["desktops"][0]["online"] is False
    assert await store.read(DESKTOP_ID) is not None


@pytest.mark.asyncio
async def test_rejected_secret_is_rate_limited_and_old_connection_loses_ownership():
    holder, _, store = service_pair(blpop_timeout=0.05)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    await wait_online(store)
    rotated = await bind(holder, secret=OTHER_SECRET)
    assert rotated.status == 200
    await asyncio.wait_for(task, timeout=2)
    assert socket.closed is True
    rejected, rejected_task = await connect(holder, secret=SECRET)
    frame = await asyncio.wait_for(rejected.sent.get(), timeout=1)
    assert frame == {"type": "rejected"}
    await rejected_task
    for _ in range(8):
        attempt, attempt_task = await connect(holder, secret=SECRET, client_ip="10.0.0.8")
        assert (await asyncio.wait_for(attempt.sent.get(), timeout=1))["type"] == "rejected"
        await attempt_task
    limited, limited_task = await connect(holder, secret=OTHER_SECRET, client_ip="10.0.0.8")
    assert (await asyncio.wait_for(limited.sent.get(), timeout=1))["type"] == "rejected"
    await limited_task
    assert holder.runtime.attachments == 0


@pytest.mark.asyncio
async def test_rpc_relays_across_services_and_ignores_unknown_responses():
    holder, caller, store = service_pair(rpc_timeout=2, blpop_timeout=0.05)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    await wait_online(store)
    call = asyncio.create_task(
        caller.rpc(
            user(),
            DESKTOP_ID,
            {"method": "session.list", "payload": {"userId": "999", "tenantId": "999"}},
        )
    )
    frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
    assert frame["path"] == "/api/v1/rpc"
    assert frame["headers"] == {"x-dsh-user-id": "7", "x-dsh-tenant-id": "3"}
    assert '"userId":"999"' in frame["body"]
    await socket.incoming.put({"type": "response", "id": "unknown", "status": 500, "headers": {}, "body": "nope"})
    await socket.incoming.put(
        {
            "type": "response",
            "id": frame["id"],
            "status": 401,
            "headers": {"content-type": "application/json"},
            "body": '{"ok":false,"error":"account_switched"}',
        }
    )
    await socket.incoming.put(
        {
            "type": "response",
            "id": frame["id"],
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": '{"ok":true,"value":1}',
        }
    )
    result = await call
    assert result.status == 401
    assert result.raw is True
    assert result.body == '{"ok":false,"error":"account_switched"}'
    await stop(task)


@pytest.mark.asyncio
async def test_stale_and_expired_requests_are_not_delivered():
    holder, _, store = service_pair(blpop_timeout=0.05, rpc_timeout=0.25)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    connection_id = await wait_online(store)
    record = await store.read(DESKTOP_ID)
    assert record is not None
    assert await store.activate(DESKTOP_ID, record.secret_hash, "replacement", 60) == connection_id
    await store.push_request(
        DESKTOP_ID,
        connection_id,
        {"kind": "rpc", "id": "stale", "deadline": time.time() + 30, "body": "{}", "userId": "7", "tenantId": "3"},
    )
    await socket.incoming.put({"type": "ping"})
    await asyncio.wait_for(task, timeout=2)
    assert socket.sent.empty()


@pytest.mark.asyncio
async def test_rpc_times_out_when_the_desktop_does_not_answer():
    holder, _, store = service_pair(rpc_timeout=0.25, blpop_timeout=0.05)
    assert (await bind(holder)).status == 200
    record = await store.read(DESKTOP_ID)
    assert record is not None
    assert await store.activate(DESKTOP_ID, record.secret_hash, "offline-holder", 60) == ""
    timed_out = await holder.rpc(user(), DESKTOP_ID, {"method": "session.list", "payload": {}})
    assert timed_out.status == 503


@pytest.mark.asyncio
async def test_attach_capacity_and_cancellation_do_not_hold_the_connection():
    holder, _, store = service_pair(blpop_timeout=5, max_attach=1)
    assert (await bind(holder)).status == 200
    _socket, task = await connect(holder)
    await wait_online(store)
    started = time.monotonic()
    await stop(task)
    assert time.monotonic() - started < 1
    holder.runtime.attachments = holder.max_attach
    limited, limited_task = await connect(holder)
    assert (await asyncio.wait_for(limited.sent.get(), timeout=1))["type"] == "rejected"
    await limited_task
    assert holder.runtime.attachments == holder.max_attach


@pytest.mark.asyncio
async def test_matching_secret_moves_the_desktop_to_the_new_account():
    holder, _, store = service_pair(blpop_timeout=0.05)
    owner = user()
    moved_owner = user(8, 4)
    assert (await bind(holder, owner)).status == 200
    socket, task = await connect(holder)
    await wait_online(store)
    rejected = await bind(holder, moved_owner, secret=OTHER_SECRET)
    assert rejected.status == 409
    assert await store.current_connection(DESKTOP_ID)
    moved = await bind(holder, moved_owner, secret=SECRET, display_name="Moved")
    assert moved.status == 200
    await asyncio.wait_for(task, timeout=2)
    assert socket.closed is True
    visible = await holder.list_desktops(moved_owner)
    hidden = await holder.list_desktops(owner)
    assert visible.body["desktops"] == [{"desktopId": DESKTOP_ID, "displayName": "Moved", "online": False}]
    assert hidden.body["desktops"] == []
    await store.add_index("3", "7", DESKTOP_ID)
    repaired = await holder.list_desktops(owner)
    assert repaired.body["desktops"] == []
    assert await store.desktop_ids("3", "7") == []
    record = await store.read(DESKTOP_ID)
    assert record is not None
    assert record.tenant_id == "4"
    assert record.user_id == "8"


@pytest.mark.asyncio
async def test_relay_failures_are_logged():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    holder = MobileAccessService(_FailingDispatchStore(redis), blpop_timeout=0.05)
    assert (await bind(holder)).status == 200
    messages = []
    handler_id = logger.add(lambda message: messages.append(str(message)))
    socket, task = await connect(holder)
    try:
        await asyncio.wait_for(task, timeout=2)
    finally:
        logger.remove(handler_id)
    assert socket.closed is True
    assert holder.runtime.attachments == 0
    assert any("mobile attach relay ended" in message for message in messages)


async def test_cross_service_timeout_clears_pending_on_idle_attached_connection(monkeypatch):
    holder, caller, store = service_pair(rpc_timeout=30, blpop_timeout=5)
    clock = [time.time()]
    monkeypatch.setattr("bisheng.dsh.domain.services.mobile_access.time", SimpleNamespace(time=lambda: clock[0]))
    idle = asyncio.Event()
    wake = asyncio.Event()
    cleaned = asyncio.Event()
    delivered = asyncio.Event()
    original_pop = store.pop_request
    pop_count = 0

    async def controlled_pop(desktop_id, connection_id, timeout):
        nonlocal pop_count
        assert 0 < timeout <= 1
        pop_count += 1
        if pop_count == 1:
            return await original_pop(desktop_id, connection_id, timeout)
        if pop_count == 2:
            idle.set()
            await wake.wait()
            return None
        cleaned.set()
        await asyncio.Event().wait()

    async def timeout_response(desktop_id, request_id, timeout):
        await delivered.wait()
        clock[0] += 31
        return None

    monkeypatch.setattr(store, "pop_request", controlled_pop)
    monkeypatch.setattr(store, "pop_response", timeout_response)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    call = None
    try:
        connection_id = await wait_online(store)
        call = asyncio.create_task(caller.rpc(user(), DESKTOP_ID, {"method": "session.list"}))
        frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        await asyncio.wait_for(idle.wait(), timeout=1)
        assert holder.runtime.pending[connection_id] == {frame["id"]: clock[0] + 30}
        assert caller.runtime.pending == {}
        delivered.set()
        result = await asyncio.wait_for(call, timeout=1)
        assert result.status == 503
        assert result.body == {"error": "offline"}
        wake.set()
        await asyncio.wait_for(cleaned.wait(), timeout=1)
        assert holder.runtime.pending[connection_id] == {}
        assert not task.done()
        assert await store.current_connection(DESKTOP_ID) == connection_id
    finally:
        if call is not None:
            await stop(call)
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)
    assert holder.runtime.pending == {}


@pytest.mark.parametrize("already_cleaned", [False, True])
async def test_late_response_does_not_create_a_response_queue(monkeypatch, already_cleaned):
    holder, _, store = service_pair()
    monkeypatch.setattr("bisheng.dsh.domain.services.mobile_access.time", SimpleNamespace(time=lambda: 100))
    holder.runtime.pending["connection"] = {} if already_cleaned else {"expired": 100}
    await holder._accept_response(
        FakeSocket(), DESKTOP_ID, "connection", {"id": "expired", "status": 200, "body": "late"}
    )
    assert holder.runtime.pending["connection"] == {}
    assert not await store.redis.exists(store.response_key(DESKTOP_ID, "expired"))


async def test_pending_capacity_returns_busy_across_services_without_dispatching():
    holder, caller, store = service_pair(rpc_timeout=5, blpop_timeout=0.05, max_pending=1)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    first_call = None
    next_call = None
    try:
        connection_id = await wait_online(store)
        first_call = asyncio.create_task(caller.rpc(user(), DESKTOP_ID, {"method": "session.list"}))
        first_frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        assert len(holder.runtime.pending[connection_id]) == 1
        busy = await asyncio.wait_for(caller.rpc(user(), DESKTOP_ID, {"method": "session.list"}), timeout=2)
        assert busy.status == 503
        assert busy.raw is True
        assert busy.media_type == "application/json"
        assert busy.body == '{"error":"busy"}'
        assert socket.sent.empty()
        assert list(holder.runtime.pending[connection_id]) == [first_frame["id"]]
        await socket.incoming.put({"type": "response", "id": first_frame["id"], "status": 200, "body": "first"})
        assert (await asyncio.wait_for(first_call, timeout=2)).body == "first"
        assert holder.runtime.pending[connection_id] == {}
        next_call = asyncio.create_task(caller.rpc(user(), DESKTOP_ID, {"method": "session.list"}))
        next_frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        await socket.incoming.put({"type": "response", "id": next_frame["id"], "status": 200, "body": "next"})
        assert (await asyncio.wait_for(next_call, timeout=2)).body == "next"
        assert holder.runtime.pending[connection_id] == {}
    finally:
        for call in (first_call, next_call):
            if call is not None:
                await stop(call)
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


class _FailingDispatchStore(MobileAccessStore):
    async def pop_request(self, desktop_id: str, connection_id: str, timeout: float) -> dict | None:
        del desktop_id, connection_id, timeout
        raise RedisError("dispatch failed")


class _CountingRedis:
    def __init__(self, inner):
        self.inner = inner
        self.blocking_reads = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def blpop(self, *args, **kwargs):
        self.blocking_reads += 1
        return await self.inner.blpop(*args, **kwargs)


@pytest.mark.asyncio
async def test_session_stream_relays_chunks_and_cancels_from_the_other_worker():
    inner = fakeredis.aioredis.FakeRedis(decode_responses=True)
    shared = _CountingRedis(inner)
    blocking = _CountingRedis(inner)
    store = MobileAccessStore(shared, blocking)
    holder = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    caller = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    opened = None
    try:
        await wait_online(store)
        opened = asyncio.create_task(caller.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"))
        frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        assert frame["method"] == "GET"
        assert frame["path"] == "/api/v1/session/stream?sessionId=session-1&view=transcript"
        # fetch refuses a GET that carries a body, even an empty one.
        assert "body" not in frame
        await socket.incoming.put(
            {
                "type": "response-start",
                "id": frame["id"],
                "status": 200,
                "headers": {"content-type": "text/event-stream"},
            }
        )
        await socket.incoming.put(
            {"type": "response-chunk", "id": frame["id"], "data": "event: snapshot\ndata: {}\n\n"}
        )
        await socket.incoming.put({"type": "response-chunk", "id": "late", "data": "ignored"})
        await socket.incoming.put({"type": "response-end", "id": frame["id"]})
        stream = await asyncio.wait_for(opened, timeout=2)
        assert stream.status == 200
        chunks = []
        async for piece in stream.body:
            chunks.append(piece)
            if len(chunks) > 4:
                break
        assert chunks[0] == ": keep-alive\n\n"
        assert "event: snapshot" in chunks[1]
        await stream.close()
        cancel = await asyncio.wait_for(socket.sent.get(), timeout=2)
        assert cancel == {"type": "cancel", "id": frame["id"]}
        assert blocking.blocking_reads >= 1
        assert caller.runtime.streams == 0
    finally:
        if opened is not None:
            await stop(opened)
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_keep_alive_never_lands_inside_a_half_delivered_event():
    inner = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(inner, inner)
    holder = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    caller = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30, keepalive_interval=0.05)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    opened = None
    piece = None
    try:
        await wait_online(store)
        opened = asyncio.create_task(caller.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"))
        frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        await socket.incoming.put({"type": "response-start", "id": frame["id"], "status": 200, "headers": {}})
        stream = await asyncio.wait_for(opened, timeout=2)
        body = stream.body.__aiter__()
        assert await asyncio.wait_for(body.__anext__(), timeout=2) == ": keep-alive\n\n"
        # One SSE event split across two desktop chunks.
        await socket.incoming.put({"type": "response-chunk", "id": frame["id"], "data": 'event: event\ndata: {"a":1'})
        assert await asyncio.wait_for(body.__anext__(), timeout=2) == 'event: event\ndata: {"a":1'
        piece = asyncio.create_task(body.__anext__())
        await asyncio.sleep(0.3)
        assert not piece.done(), "a comment was written inside an unfinished event"
        await socket.incoming.put({"type": "response-chunk", "id": frame["id"], "data": "}\n\n"})
        assert await asyncio.wait_for(piece, timeout=2) == "}\n\n"
        piece = None
        # The event is closed, so keep-alive resumes.
        assert await asyncio.wait_for(body.__anext__(), timeout=2) == ": keep-alive\n\n"
        await stream.close()
    finally:
        if piece is not None:
            await stop(piece)
        if opened is not None:
            await stop(opened)
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_a_full_request_queue_answers_busy_instead_of_opening_a_stream():
    inner = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(inner, inner)
    holder = MobileAccessService(store, blpop_timeout=0.05, max_pending=0)
    caller = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    try:
        await wait_online(store)
        result = await asyncio.wait_for(
            caller.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"), timeout=5
        )
        assert isinstance(result, MobileResult)
        assert result.status == 503
        assert result.body == '{"error":"busy"}'
        assert caller.runtime.streams == 0
    finally:
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


class _FailingBlpop:
    """Reads normally until ``fail`` is set, then behaves like a moved slot."""

    def __init__(self, inner):
        self.inner = inner
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def blpop(self, *args, **kwargs):
        if self.fail:
            raise RedisError("slot moved")
        return await self.inner.blpop(*args, **kwargs)


@pytest.mark.asyncio
async def test_a_redis_failure_mid_stream_ends_with_an_error_event():
    inner = fakeredis.aioredis.FakeRedis(decode_responses=True)
    blocking = _FailingBlpop(inner)
    store = MobileAccessStore(inner, blocking)
    holder = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    caller = MobileAccessService(store, blpop_timeout=0.05, stream_timeout=30)
    assert (await bind(holder)).status == 200
    socket, task = await connect(holder)
    opened = None
    try:
        await wait_online(store)
        opened = asyncio.create_task(caller.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"))
        frame = await asyncio.wait_for(socket.sent.get(), timeout=2)
        await socket.incoming.put({"type": "response-start", "id": frame["id"], "status": 200, "headers": {}})
        stream = await asyncio.wait_for(opened, timeout=2)
        blocking.fail = True
        pieces = [piece async for piece in stream.body]
        assert pieces[0] == ": keep-alive\n\n"
        assert pieces[-1] == 'event: error\ndata: {"error":"unavailable"}\n\n'
        await stream.close()
        assert caller.runtime.streams == 0
    finally:
        if opened is not None:
            await stop(opened)
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_a_cancelled_stream_request_still_runs_the_stream_cleanup():
    closed = asyncio.Event()
    started = asyncio.Event()

    async def body():
        yield ": keep-alive\n\n"
        started.set()
        await asyncio.sleep(30)

    async def close():
        # The real cleanup awaits Redis. Unshielded, the cancellation that
        # ended the request lands on this checkpoint and the desktop is never
        # told to drop its follow.
        await asyncio.sleep(0)
        closed.set()

    response = MobileStreamingResponse(MobileStream(200, "text/event-stream", body(), close))

    async def receive():
        await asyncio.sleep(30)
        return {"type": "http.disconnect"}

    async def send(message):
        del message

    # The server runs the request inside a cancel scope. Unlike a bare
    # task.cancel(), such a scope keeps raising at every later checkpoint,
    # which is what reaches the cleanup after the body is gone.
    async with anyio.create_task_group() as group:
        group.start_soon(response, {"type": "http"}, receive, send)
        await asyncio.wait_for(started.wait(), timeout=5)
        group.cancel_scope.cancel()
    await asyncio.wait_for(closed.wait(), timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_at", ["open", "dispatch", "first_frame"])
async def test_cancel_during_stream_open_releases_slot_and_cancels_desktop(pause_at):
    waiting = asyncio.Event()

    class PausingStore(MobileAccessStore):
        async def open_stream(self, *args):
            await super().open_stream(*args)
            if pause_at == "open":
                waiting.set()
                await asyncio.Event().wait()

        async def push_request(self, desktop_id, connection_id, message):
            await super().push_request(desktop_id, connection_id, message)
            if pause_at == "dispatch" and message.get("kind") == "stream":
                waiting.set()
                await asyncio.Event().wait()

        async def pop_response(self, *args, **kwargs):
            waiting.set()
            await asyncio.Event().wait()

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = PausingStore(redis)
    service = MobileAccessService(store, max_streams=1)
    await bind(service)
    record = await store.read(DESKTOP_ID)
    await store.activate(DESKTOP_ID, record.secret_hash, "connected", 60)
    opening = asyncio.create_task(service.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"))
    await asyncio.wait_for(waiting.wait(), timeout=2)
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    assert service.runtime.streams == 0
    messages = [json.loads(item) for item in await redis.lrange(store.request_key(DESKTOP_ID, "connected"), 0, -1)]
    cancel = messages[-1]
    assert cancel["kind"] == "cancel"
    assert await redis.get(store.stream_key(DESKTOP_ID, cancel["id"])) == "closed"
    assert await service._acquire_stream() is True
    await service._release_stream()


@pytest.mark.asyncio
async def test_stream_overflow_cancels_follow_and_emits_busy_across_workers():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis, max_stream_chunks=2)
    holder = MobileAccessService(store, blpop_timeout=0.05)
    caller = MobileAccessService(MobileAccessStore(redis), blpop_timeout=0.05)
    await bind(holder)
    socket, task = await connect(holder)
    stream = None
    try:
        connection = await wait_online(store)
        opening = asyncio.create_task(caller.open_session_stream(user(), DESKTOP_ID, "session-1", "transcript"))
        request = await asyncio.wait_for(socket.sent.get(), timeout=2)
        request_id = request["id"]
        await holder._accept_stream_frame(
            DESKTOP_ID, connection, {"type": "response-start", "id": request_id, "status": 200, "headers": {}}
        )
        stream = await asyncio.wait_for(opening, timeout=2)
        for _ in range(3):
            await holder._accept_stream_frame(
                DESKTOP_ID, connection, {"type": "response-chunk", "id": request_id, "data": "data: {}\n\n"}
            )
        assert request_id not in holder.runtime.pending[connection]
        assert await asyncio.wait_for(socket.sent.get(), timeout=2) == {"type": "cancel", "id": request_id}
        assert [part async for part in stream.body] == [": keep-alive\n\n", 'event: error\ndata: {"error":"busy"}\n\n']
        await stream.close()
        assert caller.runtime.streams == 0
        assert not await redis.exists(store.response_key(DESKTOP_ID, request_id))
        # Another worker may already be writing a final chunk when cleanup lands.
        assert await store.push_stream_response(DESKTOP_ID, request_id, {"type": "response-chunk", "data": "late"}) == 0
        assert not await redis.exists(store.response_key(DESKTOP_ID, request_id))
    finally:
        if stream is not None:
            await stream.close()
        await socket.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_stream_queue_limits_are_atomic_and_count_utf8_bytes():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis, max_stream_chunks=2, max_stream_frame_bytes=128)
    await store.open_stream(DESKTOP_ID, "concurrent", 60)
    results = await asyncio.gather(
        *(
            store.push_stream_response(DESKTOP_ID, "concurrent", {"type": "response-chunk", "data": "small"})
            for _ in range(20)
        )
    )
    assert results.count(1) == 2
    assert results.count(-1) == 1
    assert await redis.llen(store.response_key(DESKTOP_ID, "concurrent")) == 1
    assert await store.pop_response(DESKTOP_ID, "concurrent", 0.01, stream=True) == {
        "type": "response-error",
        "error": "busy",
    }
    await store.open_stream(DESKTOP_ID, "utf8", 60)
    # Character count is below 128, but the serialized UTF-8 payload is larger.
    assert await store.push_stream_response(DESKTOP_ID, "utf8", {"type": "response-chunk", "data": "汉" * 40}) == -1


@pytest.mark.asyncio
async def test_stream_queue_budget_is_reclaimed_when_the_phone_drains():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis, max_stream_chunks=2)
    await store.open_stream(DESKTOP_ID, "draining", 60)
    for index in range(20):
        frame = {"type": "response-chunk", "data": str(index)}
        assert await store.push_stream_response(DESKTOP_ID, "draining", frame) == 1
        assert await store.pop_response(DESKTOP_ID, "draining", 0.01, stream=True) == frame
    await store.close_stream(DESKTOP_ID, "draining")
    assert await store.push_stream_response(DESKTOP_ID, "draining", {"type": "response-end"}) == 0


@pytest.mark.asyncio
async def test_mobile_service_initializes_once_for_concurrent_first_requests(monkeypatch):
    import threading

    from bisheng.core.cache import redis_conn, redis_manager
    from bisheng.dsh.api.endpoints import mobile

    started, release = threading.Event(), threading.Event()
    clients = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.async_connection = object()
            self.closed = 0
            clients.append(self)
            started.set()
            assert release.wait(timeout=3)

        async def aclose(self):
            self.closed += 1

        def close(self):
            self.closed += 1

    async def shared():
        return SimpleNamespace(async_connection=object())

    monkeypatch.setattr(mobile, "_service", None)
    monkeypatch.setattr(mobile, "_blocking_redis", None)
    monkeypatch.setattr(mobile, "_service_lock", asyncio.Lock())
    monkeypatch.setattr(redis_conn, "RedisClient", Client)
    monkeypatch.setattr(redis_manager, "get_redis_client", shared)
    calls = [asyncio.create_task(mobile.mobile_service()) for _ in range(3)]
    try:
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0)
        release.set()
        services = await asyncio.gather(*calls)
        assert len(clients) == 1
        assert all(service is services[0] for service in services)
        await mobile.close_mobile_service()
        assert clients[0].closed == 2
    finally:
        release.set()
        for call in calls:
            await stop(call)


@pytest.mark.asyncio
async def test_cancelled_initialization_closes_the_unpublished_redis_client(monkeypatch):
    import threading

    from bisheng.core.cache import redis_conn, redis_manager
    from bisheng.dsh.api.endpoints import mobile

    started, release = threading.Event(), threading.Event()
    clients = []

    class Client:
        def __init__(self, *args, **kwargs):
            self.async_connection = object()
            self.closed = 0
            clients.append(self)
            started.set()
            assert release.wait(timeout=3)

        async def aclose(self):
            self.closed += 1

        def close(self):
            self.closed += 1

    async def shared():
        return SimpleNamespace(async_connection=object())

    monkeypatch.setattr(mobile, "_service", None)
    monkeypatch.setattr(mobile, "_blocking_redis", None)
    monkeypatch.setattr(mobile, "_service_lock", asyncio.Lock())
    monkeypatch.setattr(redis_conn, "RedisClient", Client)
    monkeypatch.setattr(redis_manager, "get_redis_client", shared)
    opening = asyncio.create_task(mobile.mobile_service())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        opening.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await opening
        assert mobile._service is None
        assert mobile._blocking_redis is None
        assert clients[0].closed == 2
    finally:
        release.set()
        await stop(opening)


@pytest.mark.asyncio
async def test_non_sse_stream_reply_is_bounded_without_changing_unary_rpc():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis, max_stream_frame_bytes=128)
    service = MobileAccessService(store)
    service.runtime.pending["connected"] = {"stream": time.time() + 30, "rpc": time.time() + 30}
    service.runtime.stream_requests.add("stream")
    await store.open_stream(DESKTOP_ID, "stream", 60)
    for request_id in ("stream", "rpc"):
        await service._accept_response(
            None,
            DESKTOP_ID,
            "connected",
            {"type": "response", "id": request_id, "status": 200, "body": "x" * 256},
        )
    assert await store.pop_response(DESKTOP_ID, "stream", 0.01, stream=True) == {
        "type": "response-error",
        "error": "busy",
    }
    unary = await store.pop_response(DESKTOP_ID, "rpc", 0.01)
    assert unary["status"] == 200
    assert unary["body"] == "x" * 256
    assert not service.runtime.stream_requests


@pytest.mark.asyncio
async def test_buffered_chunks_and_overflow_survive_a_short_phone_pause():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = MobileAccessStore(redis, max_stream_chunks=1)
    await store.open_stream(DESKTOP_ID, "paused", 180)
    await store.push_stream_response(DESKTOP_ID, "paused", {"type": "response-chunk", "data": "data: {}\n\n"})
    # Stream queues are bounded, so retain pending data until the stream's
    # deadline rather than silently dropping increments at the unary 60s TTL.
    assert await redis.ttl(store.response_key(DESKTOP_ID, "paused")) >= 175
    assert await store.push_stream_response(DESKTOP_ID, "paused", {"type": "response-end"}) == -1
    assert await redis.ttl(store.response_key(DESKTOP_ID, "paused")) >= 175
    await store.close_stream(DESKTOP_ID, "paused")
    assert not await redis.exists(store.response_key(DESKTOP_ID, "paused"))

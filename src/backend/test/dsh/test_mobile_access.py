"""Mobile access keeps the desktop and phone contracts while crossing workers."""

import asyncio
import contextlib
import time
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
from redis.exceptions import RedisError
from starlette.websockets import WebSocketDisconnect

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.api.endpoints.mobile import mobile_service, router
from bisheng.dsh.api.router import router as dsh_router
from bisheng.dsh.domain.services.mobile_access import MobileAccessService
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
    for path in ("/dsh/mobile/desktops", "/dsh/mobile/desktops/{desktop_id}/rpc"):
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

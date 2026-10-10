"""Only the isolated debug app may serve diagnostic events."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.eplus.api.debug_router import create_debug_router
from bisheng.eplus.domain.services.debug_admission import DebugAdmissionService
from bisheng.eplus.infrastructure.debug_gate import RedisDebugGate
from test.eplus.test_eplus_debug_admission import Authorization, Reader, snapshot


class Gate:
    @asynccontextmanager
    async def acquire(self):
        yield


class Runtime:
    async def run(self, context, request, trace):
        trace.emit("context", context.public_view())
        yield "one"
        yield "two"


def client(runtime=None, admin=True):
    app = FastAPI()
    service = DebugAdmissionService(Authorization(), Reader(snapshot()))
    app.include_router(create_debug_router(lambda: service, runtime or Runtime(), Gate()))
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=1, tenant_id=7, admin=admin, edit=True
    )
    return TestClient(app)


def test_http_rejects_scope_expansion_and_non_admin():
    assert (
        client()
        .post("/robot-debug/api/assistants/a/run", json={"query": "hi", "test_user_id": 2, "space_ids": [999]})
        .status_code
        == 422
    )
    assert client(admin=False).get("/robot-debug/api/assistants/a/context?test_user_id=2").status_code == 403


def test_cross_origin_run_is_rejected_before_execution():
    response = client().post(
        "/robot-debug/api/assistants/a/run",
        headers={"Origin": "https://other.example"},
        json={"query": "hi", "test_user_id": 2},
    )
    assert response.status_code == 403


async def test_disconnect_cancels_producer_and_releases_gate():
    stopped, released = asyncio.Event(), asyncio.Event()

    class Slow:
        async def run(self, context, request, trace):
            trace.emit("context", {})
            try:
                await asyncio.Event().wait()
                yield "late"
            finally:
                stopped.set()

    class Redis:
        async def set(self, *args, **kwargs):
            return True

        async def eval(self, *args):
            # A real network release yields, unlike a synchronous finally block.
            await asyncio.sleep(0.01)
            released.set()

    app = FastAPI()
    app.include_router(
        create_debug_router(
            lambda: DebugAdmissionService(Authorization(), Reader(snapshot())), Slow(), RedisDebugGate(Redis())
        )
    )
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=1, tenant_id=7, admin=True, edit=True
    )
    sent, incoming = [], asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": b'{"query":"hi","test_user_id":2}', "more_body": False})

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            incoming.put_nowait({"type": "http.disconnect"})

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "method": "POST",
        "scheme": "http",
        "path": "/robot-debug/api/assistants/a/run",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "server": ("test", 80),
        "client": ("test", 123),
    }
    await asyncio.wait_for(app(scope, incoming.get, send), 1)
    assert stopped.is_set() and released.is_set()
    assert not any(b"late" in m.get("body", b"") for m in sent)


def test_ordered_events_and_one_terminal_without_tool_calls():
    response = client().post("/robot-debug/api/assistants/a/run", json={"query": "hi", "test_user_id": 2})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["context", "answer_delta", "answer_delta", "completed"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert events[-1]["data"]["tool_call_count"] == 0
    assert len({e["run_id"] for e in events}) == 1


def test_failed_model_does_not_return_exception_payload():
    class Broken:
        async def run(self, context, request, trace):
            raise RuntimeError("private credentials and provider body")
            yield

    response = client(Broken()).post("/robot-debug/api/assistants/a/run", json={"query": "hi", "test_user_id": 2})
    assert "private credentials" not in response.text
    assert '"type": "failed"' in response.text


def test_deadline_cancels_underlying_execution(monkeypatch):
    import bisheng.eplus.api.debug_router as module

    stopped = []

    class Slow:
        async def run(self, context, request, trace):
            try:
                await asyncio.sleep(5)
                yield "late"
            finally:
                stopped.append(True)

    monkeypatch.setattr(module, "RUN_TIMEOUT_SECONDS", 0.01)
    response = client(Slow()).post("/robot-debug/api/assistants/a/run", json={"query": "hi", "test_user_id": 2})
    assert '"error_type": "TimeoutError"' in response.text
    assert stopped == [True]

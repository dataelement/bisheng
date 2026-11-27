"""Established-transport unit tests with real SQL session revocation."""

import asyncio

import pytest

from bisheng.user.domain.services.platform_stream import run_platform_guarded
from test.platform_auth.test_platform_session import runtime as _runtime

runtime = _runtime


def reference(service, issued):
    claims = service.decode(issued["access_token"])
    return {
        "kind": "platform_session",
        "session_id": issued["session_id"],
        "session_version": claims["session_version"],
        "user_id": int(claims["sub"]),
        "tenant_id": int(claims["tenant_id"]),
        "token_version": claims["token_version"],
        "expires_at": issued["access_expires_at"],
    }


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_revoked_next_websocket_message_never_reaches_business(runtime, native_client):
    """AC-16/26: Every incoming WS action rechecks its exact session."""
    service, _, _ = runtime
    issued = await service.issue(7, 9, native_client)
    accepted = asyncio.Event()
    messages, output, business = asyncio.Queue(), [], []

    async def app(scope, receive, send):
        await send({"type": "websocket.accept"})
        accepted.set()
        message = await receive()
        business.append(message)

    async def send(message):
        output.append(message)

    guarded = asyncio.create_task(
        run_platform_guarded(
            app,
            {"type": "websocket"},
            messages.get,
            send,
            service=service,
            reference=reference(service, issued),
            interval=0.05,
            budget=0.1,
        )
    )
    await accepted.wait()
    await service.logout(issued["access_token"])
    await messages.put({"type": "websocket.receive", "text": "business-action"})
    await asyncio.wait_for(guarded, timeout=1)
    assert business == []
    assert output[-1]["type"] == "websocket.close" and output[-1]["code"] == 1008


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_idle_sse_stops_without_waiting_for_next_output(runtime, native_client):
    """AC-16: An idle established stream notices logout without waiting for output."""
    service, _, _ = runtime
    issued = await service.issue(7, 9, native_client)
    started, blocked, output = asyncio.Event(), asyncio.Event(), []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        started.set()
        await blocked.wait()

    async def send(message):
        output.append(message)

    task = asyncio.create_task(
        run_platform_guarded(
            app,
            {"type": "http"},
            blocked.wait,
            send,
            service=service,
            reference=reference(service, issued),
            interval=0.01,
            budget=0.1,
        )
    )
    await started.wait()
    await service.logout(issued["access_token"])
    await asyncio.wait_for(task, timeout=1)
    assert output[-1]["more_body"] is False
    assert b"session_revoked" in output[-1]["body"]


@pytest.mark.parametrize("native_client", ["bisheng-mobile", "bisheng-desktop"])
async def test_slow_storage_budget_is_retryable_and_does_not_admit_action(runtime, monkeypatch, native_client):
    """AC-17/28: A bounded storage timeout is 503; business is not admitted."""
    service, _, _ = runtime
    issued = await service.issue(7, 9, native_client)
    ref = reference(service, issued)
    output, business = [], []

    async def slow_read(reference):
        await asyncio.sleep(1)

    monkeypatch.setattr(service, "validate_reference", slow_read)

    async def app(scope, receive, send):
        message = await receive()
        business.append(message)

    async def receive():
        return {"type": "websocket.receive", "text": "action"}

    async def send(message):
        output.append(message)

    await run_platform_guarded(
        app, {"type": "websocket"}, receive, send, service=service, reference=ref, interval=0.01, budget=0.02
    )
    assert business == [] and output[-1]["code"] == 1013

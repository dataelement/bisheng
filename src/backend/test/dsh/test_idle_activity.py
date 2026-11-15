"""AC-IDLE-02/03/05/07: authentication-bound activity, independent of business admission."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import HTTPConnection

from bisheng.core.session_activity import business_activity, record_authenticated_activity
from bisheng.dsh.application.session_activity import DshSessionActivity
from bisheng.dsh.domain.services import web_session
from test.dsh import test_idle_sessions as idle_tests

native = idle_tests.native
idle = idle_tests.idle


@business_activity()
async def http_business():
    pass


@business_activity(http=False, websocket_actions=("input", "init_data"))
async def websocket_business():
    pass


@business_activity(http=False, rpc_methods=("tools/call",))
async def mcp_business():
    pass


def connection(endpoint=http_business, transport="http"):
    return HTTPConnection({"type": transport, "endpoint": endpoint, "path": "/business", "headers": []})


@pytest.mark.parametrize("transport", ["http", "websocket"])
async def test_cookie_auth_binds_exact_device_but_only_business_entrance_renews(idle, monkeypatch, transport):
    runtime, engine, clock = idle
    first, second = await idle_tests.login(runtime), await idle_tests.login(runtime)
    start = clock[0]
    clock[0] += timedelta(days=13)
    runtime.access.authenticate = AsyncMock(return_value=idle_tests.actor(second))
    redis = SimpleNamespace(get=AsyncMock(return_value="Bearer verified-desktop"))
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=redis))
    subject = {"dsh_web_session": "x" * 43, "tenant_id": 2, "user_id": 20}
    conn = connection(http_business if transport == "http" else websocket_business, transport)
    with (
        patch("bisheng.dsh.access_runtime.get_runtime", AsyncMock(return_value=runtime)),
        patch("bisheng.dsh.access_runtime.get_settings"),
    ):
        await web_session.validate_web_session(conn, subject)
    assert idle_tests.stored(engine, second).last_activity_at == start
    assert isinstance(conn.state.authenticated_activity, DshSessionActivity)
    if transport == "http":
        await record_authenticated_activity(conn)
        await record_authenticated_activity(conn)
    else:
        await record_authenticated_activity(conn, message={"action": "check_status"})
        assert idle_tests.stored(engine, second).last_activity_at == start
        await record_authenticated_activity(conn, message={"action": "input"})
    assert idle_tests.stored(engine, second).last_activity_at == clock[0]
    assert idle_tests.stored(engine, first).last_activity_at == start


async def test_http_activity_is_once_per_request_and_never_uses_client_supplied_identity():
    conn = connection()
    record = AsyncMock()
    conn.state.authenticated_activity = DshSessionActivity(
        SimpleNamespace(record_activity=record), idle_tests.actor({"session_id": "verified"})
    )
    await record_authenticated_activity(conn)
    await record_authenticated_activity(conn)
    record.assert_awaited_once()
    assert record.await_args.args[0].session_id == "verified"


@pytest.mark.parametrize(
    "endpoint,message",
    [
        (websocket_business, None),
        (websocket_business, {"action": "check_status"}),
        (websocket_business, {"action": "stop"}),
        (websocket_business, {"action": []}),
        (mcp_business, {"method": "tools/list"}),
        (mcp_business, {"method": "resources/list"}),
        (mcp_business, {"method": "ping"}),
        (mcp_business, {"method": {}}),
    ],
)
async def test_transport_maintenance_and_malformed_messages_do_not_renew(endpoint, message):
    conn = connection(endpoint, "websocket" if endpoint is websocket_business else "http")
    record = AsyncMock()
    conn.state.authenticated_activity = DshSessionActivity(
        SimpleNamespace(record_activity=record), idle_tests.actor({"session_id": "verified"})
    )
    await record_authenticated_activity(conn, message=message)
    record.assert_not_awaited()


async def test_plain_web_and_untrusted_duck_typed_callbacks_are_noops():
    conn = connection()
    await record_authenticated_activity(conn)
    untrusted = conn.state.authenticated_activity = SimpleNamespace(record=AsyncMock())
    await record_authenticated_activity(conn)
    untrusted.record.assert_not_awaited()


async def test_mcp_activity_counts_calls_even_when_tool_permission_will_be_denied():
    conn = connection(mcp_business)
    record = AsyncMock()
    conn.state.authenticated_activity = DshSessionActivity(
        SimpleNamespace(record_activity=record), idle_tests.actor({"session_id": "verified"})
    )
    await record_authenticated_activity(conn, message={"method": "tools/call", "params": {"name": "not-authorized"}})
    record.assert_awaited_once()

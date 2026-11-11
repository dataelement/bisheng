"""AC-IDLE-02/03/07: business admission renews; discovery and cookie checks do not."""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from bisheng.common.errcode.dsh import DshModelNotAllowedError, DshSessionExpiredError, DshUpstreamTimeoutError
from bisheng.dsh.domain.services import web_session
from bisheng.dsh.domain.services.tools import ToolInvocationService
from bisheng.user.domain.services.auth import LoginUser
from test.dsh import test_idle_sessions as idle_tests
from test.dsh import test_model_service as model_tests
from test.dsh import test_work_capabilities as work_tests

native = idle_tests.native
idle = idle_tests.idle
service_setup = model_tests.service_setup


async def test_model_catalog_does_not_renew_but_admitted_chat_does(service_setup):
    service, llm, _ledger, _policy, state = service_setup
    activity = service.activity_recorder = AsyncMock()
    await service.list_models(model_tests.principal())
    activity.assert_not_awaited()
    state["online"] = False
    with pytest.raises(DshModelNotAllowedError):
        await service.complete(model_tests.principal(), model_tests.request())
    activity.assert_not_awaited()
    state["online"] = True
    await service.complete(model_tests.principal(), model_tests.request())
    activity.assert_awaited_once_with(model_tests.principal())
    assert llm.calls == 1


async def test_model_activity_failure_prevents_upstream_and_releases_admission_with_zero_usage(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    service.activity_recorder = AsyncMock(side_effect=DshSessionExpiredError())
    with pytest.raises(DshSessionExpiredError):
        await service.complete(model_tests.principal(), model_tests.request())
    assert llm.calls == 0
    assert ledger.events[-1].status == "FAILED"
    assert ledger.events[-1].total_tokens == 0
    assert ledger.used == 90


async def test_upstream_failure_still_counts_as_business_activity(service_setup):
    service, llm, _ledger, _policy, _state = service_setup
    service.activity_recorder = AsyncMock()
    llm.ainvoke = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(DshUpstreamTimeoutError):
        await service.complete(model_tests.principal(), model_tests.request())
    service.activity_recorder.assert_awaited_once()


@pytest.mark.parametrize("failure", ["prepare", "activity", None])
async def test_tool_activity_is_after_validation_and_before_external_execution(failure):
    tools = SimpleNamespace(
        prepare=AsyncMock(return_value=(object(), {"q": "hi"})),
        execute=AsyncMock(return_value="ok"),
    )
    leases = SimpleNamespace(acquire=AsyncMock(return_value="lease"), release=AsyncMock())
    activity = AsyncMock()
    if failure == "prepare":
        tools.prepare.side_effect = PermissionError()
    if failure == "activity":
        activity.side_effect = DshSessionExpiredError()
    service = ToolInvocationService(tools, leases, activity_recorder=activity)
    if failure:
        with pytest.raises((PermissionError, DshSessionExpiredError)):
            await service.invoke(model_tests.principal(), "search", {"q": "hi"})
        tools.execute.assert_not_awaited()
    else:
        await service.invoke(model_tests.principal(), "search", {"q": "hi"})
        activity.assert_awaited_once()
        tools.execute.assert_awaited_once()
    if failure == "prepare":
        activity.assert_not_awaited()
        leases.acquire.assert_not_awaited()
    else:
        leases.release.assert_awaited_once()


async def test_work_tool_discovery_does_not_renew_and_execution_does():
    service = work_tests.service()
    service.user = LoginUser.model_construct(user_id=42, tenant_id=2)
    recorder = service.user._business_activity_recorder = AsyncMock()
    await service.list_tools()
    recorder.assert_not_awaited()
    with pytest.raises(HTTPException):
        await service.call_tool("bisheng_tool_999", {})
    recorder.assert_not_awaited()
    # Use the published tool's actual executable schema.
    tools = await service.list_tools()
    name = tools[0]["name"]
    schema = tools[0]["inputSchema"]
    arguments = dict.fromkeys(schema.get("required", []), "hi")
    await service.call_tool(name, arguments)
    recorder.assert_awaited_once()


async def test_untyped_identity_cannot_supply_an_activity_hook():
    from bisheng.common.dependencies.user_deps import record_business_activity

    untrusted = SimpleNamespace(record_business_activity=AsyncMock())
    await record_business_activity(untrusted)
    untrusted.record_business_activity.assert_not_awaited()


@pytest.mark.parametrize("transport", ["http", "websocket"])
async def test_verified_cookie_binds_exact_device_without_renewing_during_validation(idle, monkeypatch, transport):
    """AC-IDLE-05/07: cookie checks read only; a business hook touches one grant."""
    from datetime import timedelta

    runtime, engine, clock = idle
    first, second = await idle_tests.login(runtime), await idle_tests.login(runtime)
    start = clock[0]
    clock[0] += timedelta(days=13)
    runtime.access.authenticate = AsyncMock(return_value=idle_tests.actor(second))
    redis = SimpleNamespace(get=AsyncMock(return_value="Bearer verified-desktop"))
    monkeypatch.setattr(web_session, "session_store", AsyncMock(return_value=redis))
    subject = {"dsh_web_session": "x" * 43, "tenant_id": 2, "user_id": 20, "user_name": "Alice"}
    connection = SimpleNamespace(state=State())
    user = LoginUser.model_construct(user_id=20, tenant_id=2)
    secret = "synthetic-cookie-signing-key-at-least-32"
    cookie = jwt.encode(
        {"sub": json.dumps(subject), "iss": "fixture", "exp": int(time.time()) + 300},
        secret,
        algorithm="HS256",
    )
    connection.cookies = {"access_token_cookie": cookie}
    auth = SimpleNamespace(
        req=connection,
        get_subject=lambda **_kwargs: subject,
        _access_cookie_key="access_token_cookie",
        jwt_secret=secret,
        cookie_conf=SimpleNamespace(jwt_iss="fixture"),
        _decode_algorithms=["HS256"],
    )
    auth.request_access_token = lambda: connection.cookies.get(auth._access_cookie_key)
    with (
        patch("bisheng.dsh.access_runtime.get_runtime", AsyncMock(return_value=runtime)),
        patch("bisheng.dsh.access_runtime.get_settings"),
        patch.object(LoginUser, "init_login_user", AsyncMock(return_value=user)),
    ):
        if transport == "http":
            # HTTP middleware performs this check before the login dependency.
            await web_session.validate_web_session(connection, subject)
            bound = await LoginUser.get_login_user(auth)
        else:
            bound = await LoginUser.get_login_user_from_ws(connection, auth)
    assert idle_tests.stored(engine, second).last_activity_at == start
    await bound.record_business_activity()
    assert idle_tests.stored(engine, second).last_activity_at == clock[0]
    assert idle_tests.stored(engine, first).last_activity_at == start
    assert "activity" not in str(bound.model_dump())


async def test_regular_web_identity_has_no_desktop_activity_hook():
    user = LoginUser.model_construct(user_id=20, tenant_id=2)
    await user.record_business_activity()
    assert user._business_activity_recorder is None

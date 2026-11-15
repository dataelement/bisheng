"""AC-IDLE-03: authentication and actual entrance dispatch own session activity."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.common.services.config_service import settings
from bisheng.core.config.dsh import DshSettings
from bisheng.core.context import tenant
from bisheng.dsh import runtime as composition
from bisheng.dsh.api.endpoints import models
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.services import chat_credits
from bisheng.dsh.domain.services.usage import DshUsageService
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from bisheng.dsh.infrastructure.quota_topology import create_quota_redis
from test.dsh import test_idle_sessions as idle_tests
from test.dsh.test_idle_sessions_http import http_idle as http_idle
from test.dsh.test_idle_sessions_http import idle as idle
from test.dsh.test_idle_sessions_http import native as native
from test.dsh.test_idle_sessions_http import service_setup as service_setup


@pytest.mark.parametrize("outcome", ["permission", "quota", "upstream"])
async def test_authenticated_dsh_request_renews_even_when_business_rejects(http_idle, outcome):
    app, runtime, engine, clock, llm = http_idle
    from test.dsh.test_idle_sessions_http import browser_login, refresh

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        issued = await browser_login(client, "/api/v1/dsh")
        clock[0] += timedelta(days=13)
        current = (await refresh(client, "/api/v1/dsh", issued["refresh_token"])).json()
        model_runtime = await models.get_model_runtime(runtime)
        if outcome == "permission":
            model_runtime.model.policy_reader = AsyncMock(side_effect=DshModelNotAllowedError())
        elif outcome == "quota":
            model_runtime.model.usage.check_and_start = AsyncMock(side_effect=QuotaRejected("quota_exceeded"))
        else:
            llm.ainvoke = AsyncMock(side_effect=TimeoutError())
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer " + current["access_token"]},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert response.status_code == {"permission": 403, "quota": 429, "upstream": 504}[outcome], response.text
        row = idle_tests.stored(engine, issued)
        assert row.last_activity_at == clock[0]
        assert row.expires_at == clock[0] + timedelta(days=14)


async def test_invalid_auth_never_renews_or_enters_business(http_idle):
    from test.dsh.test_idle_sessions_http import browser_login

    app, _runtime, engine, clock, llm = http_idle
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        issued = await browser_login(client, "/api/v1/dsh")
        before = idle_tests.stored(engine, issued)
        clock[0] += timedelta(days=14)
        r = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer " + issued["access_token"]},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert r.status_code == 401
        assert idle_tests.stored(engine, issued).last_activity_at == before.last_activity_at
        assert llm.calls == 0


@pytest.mark.parametrize("app_type", ["daily_chat", "linsight"])
async def test_normal_chat_wrapper_uses_real_factory_without_device_sessions(monkeypatch, app_type):
    """Real wrapper -> admission -> real factory -> provider -> settlement; no datastore IO."""
    monkeypatch.setitem(
        settings.__dict__, "dsh", DshSettings(enabled=True, platform_public_url="https://platform.example")
    )
    monkeypatch.setattr(tenant, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(
        CurrentIdentityRecords,
        "get",
        AsyncMock(return_value=SimpleNamespace(active=True, tenant_active=True, natural_person=True)),
    )
    monkeypatch.setattr(
        composition,
        "read_policy",
        AsyncMock(
            return_value=SimpleNamespace(
                allowed_model_ids=[7],
                rows=[SimpleNamespace(model_id=7, credit_rate=100)],
                version=1,
                quota_epoch=1,
                monthly_token_limit=10000,
            )
        ),
    )
    redis = create_quota_redis("redis://127.0.0.1:1/0")
    monkeypatch.setattr(composition, "create_quota_redis", lambda *_: redis)
    monkeypatch.setattr(composition.ModelRuntime, "activate", AsyncMock())
    admission = AsyncMock(side_effect=lambda event, **_: event)
    settlement = AsyncMock()
    monkeypatch.setattr(DshUsageService, "check_and_start", admission)
    monkeypatch.setattr(DshUsageService, "record_usage", settlement)
    model = SimpleNamespace(app_type=app_type, user_id=20, model_info=SimpleNamespace(id=7))
    provider = AsyncMock(
        return_value=AIMessage(
            content="hello", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        )
    )

    @chat_credits.account_async
    async def generate(model):
        return await provider()

    try:
        result = await generate(model)
        assert result.content == "hello"
        provider.assert_awaited_once()
        admission.assert_awaited_once()
        settlement.assert_awaited_once()
        holder = chat_credits._runtimes[asyncio.get_running_loop()]
        assert not hasattr(holder, "sessions")
        assert not hasattr(holder.models.model, "activity_recorder")
        assert await composition.get_model_runtime(holder) is holder.models
    finally:
        chat_credits._runtimes.pop(asyncio.get_running_loop(), None)
        await redis.aclose()


@pytest.mark.parametrize("status", [200, 403, 429, 500])
@pytest.mark.parametrize("desktop", [True, False])
async def test_real_web_login_dependency_renews_bound_device_before_business_result(
    http_idle, monkeypatch, status, desktop
):
    """Actual JWT dependency + cookie bridge + SQL; no business-layer activity hook."""
    import json
    from datetime import UTC

    import jwt
    from fastapi import Depends, FastAPI, HTTPException, Request

    from bisheng.dsh.domain.services import web_session
    from bisheng.user.domain.services.auth import AuthJwt, LoginUser
    from bisheng.workstation.api.endpoints import chat as workstation_http

    _, runtime, engine, clock, _ = http_idle
    first, second = await idle_tests.login(runtime), await idle_tests.login(runtime)
    start = clock[0]
    clock[0] += timedelta(days=13)
    refreshed = await runtime.sessions.refresh(second["refresh_token"])
    subject = {"user_id": 20, "user_name": "Alice", "tenant_id": 2, "token_version": 0}
    if desktop:
        subject["dsh_web_session"] = "x" * 43
    secret = "synthetic-entry-signing-key-for-local-tests"
    monkeypatch.setattr("bisheng.user.domain.services.jwt_secret.resolve_jwt_secret", lambda: secret)
    monkeypatch.setattr(
        LoginUser, "init_login_user", AsyncMock(return_value=LoginUser.model_construct(user_id=20, tenant_id=2))
    )
    monkeypatch.setattr(
        web_session,
        "session_store",
        AsyncMock(return_value=SimpleNamespace(get=AsyncMock(return_value="Bearer " + refreshed["access_token"]))),
    )
    monkeypatch.setattr("bisheng.dsh.access_runtime.get_runtime", AsyncMock(return_value=runtime))
    app = FastAPI()

    @app.middleware("http")
    async def verified_cookie_bridge(request: Request, call_next):
        verified = AuthJwt(request).get_subject()
        if "dsh_web_session" in verified:
            await web_session.validate_web_session(request, verified)
        return await call_next(request)

    async def business(_request, _data, _user):
        row = idle_tests.stored(engine, second)
        assert row.last_activity_at == (clock[0] if desktop else start)
        if status != 200:
            raise HTTPException(status_code=status)
        return {"ok": True}

    monkeypatch.setattr(workstation_http, "stream_chat_completion", business)
    app.include_router(workstation_http.router, prefix="/api/v1/workstation")

    @app.get("/poll")
    async def poll(user=Depends(LoginUser.get_login_user)):
        return {"ok": True}

    cookie = jwt.encode(
        {
            "sub": json.dumps(subject),
            "iss": settings.cookie_conf.jwt_iss,
            "exp": int(clock[0].replace(tzinfo=UTC).timestamp()) + 300,
        },
        secret,
        algorithm="HS256",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://platform.example", cookies={"access_token_cookie": cookie}
    ) as client:
        assert (await client.get("/poll")).status_code == 200
        assert idle_tests.stored(engine, second).last_activity_at == start
        assert (
            await client.post(
                "/api/v1/workstation/chat/completions",
                json={"clientTimestamp": "fixture", "model": "42", "text": "hello"},
            )
        ).status_code == status
        assert idle_tests.stored(engine, first).last_activity_at == start


async def test_native_http_chat_uses_real_model_runtime_composition(http_idle, monkeypatch):
    """Actual login/token/HTTP auth -> real runtime factory -> real model service -> fake provider."""
    from bisheng.dsh.audit_runtime import ModelAuditRuntime
    from bisheng.dsh.infrastructure import model_capabilities
    from bisheng.llm.domain.services.llm import LLMService
    from test.dsh.test_idle_sessions_http import browser_login, refresh

    app, runtime, engine, clock, llm = http_idle
    fixture_model = (await models.get_model_runtime(runtime)).model
    runtime.settings = DshSettings(enabled=True, platform_public_url="https://platform.example")
    redis = create_quota_redis("redis://127.0.0.1:1/0")
    monkeypatch.setattr(composition, "create_quota_redis", lambda *_: redis)
    monkeypatch.setattr(composition, "read_policy", fixture_model.policy_reader)
    monkeypatch.setattr(composition.ModelRuntime, "activate", AsyncMock())
    monkeypatch.setattr(DshUsageService, "read_usage", AsyncMock(return_value={"used": 0}))
    monkeypatch.setattr(DshUsageService, "check_and_start", AsyncMock(side_effect=lambda event, **_: event))
    monkeypatch.setattr(DshUsageService, "record_usage", AsyncMock())
    monkeypatch.setattr(LLMService, "get_dsh_model_snapshot", fixture_model.model_loader)
    monkeypatch.setattr(LLMService, "build_dsh_llm", lambda *_a, **_kw: llm)
    monkeypatch.setattr(model_capabilities, "desktop_model_capabilities", fixture_model.capabilities_for)
    monkeypatch.setattr(ModelAuditRuntime, "capture", AsyncMock(return_value=None))
    monkeypatch.setattr(models, "get_model_runtime", composition.get_model_runtime)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
            issued = await browser_login(client, "/api/v1/dsh")
            clock[0] += timedelta(days=13)
            current = (await refresh(client, "/api/v1/dsh", issued["refresh_token"])).json()
            r = await client.post(
                "/api/v1/dsh/chat/completions",
                headers={"Authorization": "Bearer " + current["access_token"]},
                json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hello"}]},
            )
            assert r.status_code == 200, r.text
            assert llm.calls == 1
            assert idle_tests.stored(engine, issued).last_activity_at == clock[0]
            assert not hasattr(runtime.models.model, "activity_recorder")
    finally:
        await redis.aclose()


async def test_activity_storage_failure_stays_service_unavailable_and_skips_business(http_idle):
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
    from test.dsh.test_idle_sessions_http import browser_login, refresh

    app, runtime, engine, clock, llm = http_idle
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        issued = await browser_login(client, "/api/v1/dsh")
        start = clock[0]
        clock[0] += timedelta(days=13)
        current = (await refresh(client, "/api/v1/dsh", issued["refresh_token"])).json()
        runtime.sessions.record_activity = AsyncMock(side_effect=DshAuthorizationUnavailableError())
        models.get_model_runtime.reset_mock()
        r = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer " + current["access_token"]},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert r.status_code == 503, r.text
        models.get_model_runtime.assert_not_awaited()
        assert llm.calls == 0
        row = idle_tests.stored(engine, issued)
        assert row.state == "ACTIVE" and row.last_activity_at == start


async def test_stream_records_once_before_chunks_and_does_not_renew_per_chunk(http_idle):
    from test.dsh.test_idle_sessions_http import browser_login, refresh

    app, runtime, engine, clock, llm = http_idle
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://platform.example") as client:
        issued = await browser_login(client, "/api/v1/dsh")
        clock[0] += timedelta(days=13)
        entered = clock[0]
        current = (await refresh(client, "/api/v1/dsh", issued["refresh_token"])).json()
        record = runtime.sessions.record_activity = AsyncMock(wraps=runtime.sessions.record_activity)
        original = llm.astream
        llm.continue_stream.set()

        async def stream(*args, **kwargs):
            async for part in original(*args, **kwargs):
                clock[0] += timedelta(minutes=1)
                yield part

        llm.astream = stream
        r = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer " + current["access_token"]},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hello"}], "stream": True},
        )
        assert r.status_code == 200, r.text
        assert "[DONE]" in r.text
        record.assert_awaited_once()
        assert idle_tests.stored(engine, issued).last_activity_at == entered
        assert clock[0] > entered

"""Composition and security-boundary unit coverage; no deployment middleware required."""

import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket
from bisheng.user.domain.repositories.platform_session import PlatformSessionRepository
from bisheng.user.domain.services.platform_origin import public_origin
from bisheng.user.domain.services.platform_session import PlatformSessionService
from bisheng.user.domain.services.platform_transport import require_origin


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    if not os.getenv("config"):
        path = tmp_path / "unit-platform-auth.yaml"
        path.write_text("database_url: sqlite://\nredis_url: redis://localhost:6379/1\n")
        monkeypatch.setenv("config", str(path))


@pytest.fixture
def actual_identity_service(tmp_path, settings_env):
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    engine = create_engine(f"sqlite:///{tmp_path}/unit-platform-identity.db")
    tables = [t.__table__ for t in (User, Tenant, UserTenant, PlatformSession, PlatformRefreshToken, PlatformWebTicket)]
    SQLModel.metadata.create_all(engine, tables=tables)
    with Session(engine) as db, db.begin():
        db.add(User(user_id=701, user_name="unit-platform-auth-person", password=secrets.token_hex(16)))
        db.add(Tenant(id=901, tenant_code="unit-platform-auth-home", tenant_name="Unit isolated home"))
        db.add(UserTenant(user_id=701, tenant_id=901, is_active=1, status="active"))

    @contextmanager
    def scope():
        with Session(engine) as db, db.begin():
            yield PlatformSessionRepository(db)

    return PlatformSessionService(scope, secret="unit-platform-isolated-secret"), engine


@pytest.mark.parametrize("change", ["disabled_user", "disabled_tenant", "home_changed", "token_version"])
async def test_real_identity_rows_revoke_existing_platform_session(actual_identity_service, change):
    """AC-02/10/26: Actual user, Home membership and tenant rows control admission."""
    from sqlmodel import select

    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    service, engine = actual_identity_service
    issued = await service.issue(701, 901, "bisheng-mobile")
    with Session(engine) as db, db.begin():
        if change == "disabled_user":
            row = db.get(User, 701)
            row.delete = 1
        elif change == "disabled_tenant":
            row = db.get(Tenant, 901)
            row.status = "disabled"
        elif change == "token_version":
            row = db.get(User, 701)
            row.token_version += 1
        else:
            row = db.exec(select(UserTenant).where(UserTenant.user_id == 701)).first()
            row.is_active = 0
        db.add(row)
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.inspect(issued["access_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.refresh(issued["refresh_token"])


def test_model_discovery_and_repeatable_schema_bootstrap(tmp_path):
    """AC-29/30: Fresh and repeated schema bootstrap discover all platform tables."""
    from sqlalchemy import inspect

    from bisheng.core.database.model_discovery import discover_sqlmodel_module_names

    assert "bisheng.user.domain.models.platform_session" in discover_sqlmodel_module_names()
    engine = create_engine(f"sqlite:///{tmp_path}/unit-platform-schema.db")
    tables = [m.__table__ for m in (PlatformSession, PlatformRefreshToken, PlatformWebTicket)]
    SQLModel.metadata.create_all(engine, tables=tables)
    SQLModel.metadata.create_all(engine, tables=tables, checkfirst=True)
    for table in tables:
        columns = {c["name"] for c in inspect(engine).get_columns(table.name)}
        assert {"tenant_id", "create_time", "update_time"} <= columns
        assert any(index["column_names"] == ["tenant_id"] for index in inspect(engine).get_indexes(table.name))


def test_policy_configuration_validation(settings_env):
    """AC-05/06/25: Invalid TTL and an unsafe partial mobile cutover fail startup."""
    from pydantic import ValidationError

    from bisheng.core.config.settings import PlatformAuthSettings

    with pytest.raises(ValidationError):
        PlatformAuthSettings(access_ttl_seconds=1000, idle_ttl_seconds=60)
    with pytest.raises(ValidationError):
        PlatformAuthSettings(reject_legacy_web_tokens=True, mobile_cutover_ready=False)
    with pytest.raises(ValidationError):
        PlatformAuthSettings(public_origin="https://public.test/path")
    conf = PlatformAuthSettings(reject_legacy_web_tokens=True, mobile_cutover_ready=True)
    assert conf.minimum_client_version == "1.1.0" and conf.access_ttl_seconds == 2592000


def test_model_delete_consumer_accepts_closed_platform_reference(settings_env):
    """AC-26: Model confirmation queues retain the platform Session authority."""
    from bisheng.llm.domain.repositories.model_delete_plan_repository import ModelDeletePlanRepository
    from bisheng.permission.application.data_scope import DATA_SCOPE_ALL

    credential = {
        "kind": "platform_session",
        "session_id": "a" * 32,
        "session_version": 1,
        "user_id": 701,
        "tenant_id": 901,
        "token_version": 0,
        "expires_at": (datetime.utcnow() + timedelta(days=1)).isoformat(),
    }
    actor = {"tenant_id": 901, "actor_user_id": 701, "credential_reference": credential, "data_scope": DATA_SCOPE_ALL}
    assert ModelDeletePlanRepository._actor(actor, 901)["credential_reference"] == credential
    credential["raw_token"] = "forbidden"
    with pytest.raises(ValueError):
        ModelDeletePlanRepository._actor(actor, 901)


@pytest.mark.parametrize(
    "peer,forwarded,allowed",
    [
        ("127.0.0.1", "http://localhost:3001", True),
        ("127.0.0.1", "http://localhost:4001", True),
        ("203.0.113.5", "https://public.test", False),
    ],
)
def test_origin_only_honors_trusted_proxy(peer, forwarded, allowed):
    """AC-27: Vite's trusted loopback proxy preserves Origin; an internet peer cannot forge it."""
    from urllib.parse import urlsplit

    from fastapi import FastAPI
    from starlette.requests import Request

    origin = urlsplit(forwarded)
    app = FastAPI()
    app.state.platform_auth_settings = SimpleNamespace(public_origin=None, trusted_proxy_hosts=["127.0.0.1", "::1"])
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("127.0.0.1", 7860),
            "client": (peer, 5000),
            "path": "/api/v1/auth/refresh",
            "headers": [
                (b"host", b"127.0.0.1:7860"),
                (b"origin", forwarded.encode()),
                (b"x-forwarded-host", origin.netloc.encode()),
                (b"x-forwarded-proto", origin.scheme.encode()),
            ],
            "app": app,
        }
    )
    if allowed:
        require_origin(request)
        assert public_origin(request) == forwarded
    else:
        with pytest.raises(PlatformAuthError, match="csrf_rejected"):
            require_origin(request)


async def test_disabled_issuance_keeps_existing_refresh_and_revocation(actual_identity_service):
    """AC-29: Disabling new issuance never removes the platform validation/refresh floor."""
    service, _ = actual_identity_service
    issued = await service.issue(701, 901, "bisheng-mobile")
    service.issuance_enabled_reader = lambda: False
    with pytest.raises(PlatformAuthError, match="auth_service_unavailable"):
        await service.issue(701, 901, "bisheng-mobile")
    await service.inspect(issued["access_token"])
    refreshed = await service.refresh(issued["refresh_token"])
    await service.logout(refreshed["access_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.inspect(refreshed["access_token"])


@pytest.mark.parametrize("code,http_status", [(10600, 401), (10607, 400), (10620, 403), (10621, 403), (10601, 401)])
async def test_password_failure_keeps_business_code_and_issues_no_session(settings_env, monkeypatch, code, http_status):
    """AC-02: Existing password policy errors keep their code and never create a session."""
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient

    from bisheng.common.schemas.api import UnifiedResponseModel
    from bisheng.user.application import platform_auth
    from test.platform_auth.test_platform_api import app_for

    service = SimpleNamespace(issue=AsyncMock())
    monkeypatch.setattr(
        platform_auth,
        "validate_password_identity",
        AsyncMock(
            return_value=UnifiedResponseModel(status_code=code, status_message="historical password policy", data=None)
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app_for(service)), base_url="https://platform.test") as client:
        result = await client.post(
            "/api/v1/auth/login",
            json={
                "user_name": "unit-platform-login",
                "password": "encrypted",
                "client_id": "bisheng-mobile",
                "client_version": "1.1.0",
            },
        )
        assert result.status_code == http_status and result.json()["status_code"] == code
        service.issue.assert_not_called()


async def test_old_mobile_cutover_dependency_returns_426_before_legacy_service(settings_env, monkeypatch):
    """AC-25: The old mobile session entry refuses cutover with a readable upgrade contract."""
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.api.endpoints.mobile import mobile_sessions

    monkeypatch.setattr(settings.platform_auth, "mobile_cutover_ready", True)
    monkeypatch.setattr(settings.platform_auth, "minimum_client_version", "1.1.0")
    with pytest.raises(PlatformAuthError) as caught:
        await mobile_sessions(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
    assert caught.value.http_status == 426
    assert caught.value.payload()["data"]["minimum_client_version"] == "1.1.0"
    assert "升级" in caught.value.payload()["message"]


async def test_native_minimum_version_is_checked_before_password_validation(settings_env, monkeypatch):
    """AC-25: Old protocol clients cannot trigger a new platform login after cutover."""
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient

    from bisheng.common.services.config_service import settings
    from bisheng.user.application import platform_auth
    from test.platform_auth.test_platform_api import app_for

    monkeypatch.setattr(settings.platform_auth, "mobile_cutover_ready", True)
    identity = AsyncMock()
    monkeypatch.setattr(platform_auth, "validate_password_identity", identity)
    async with AsyncClient(transport=ASGITransport(app=app_for(None)), base_url="https://platform.test") as client:
        result = await client.post(
            "/api/v1/auth/login",
            json={
                "user_name": "unit-platform-auth",
                "password": "cipher",
                "client_id": "bisheng-mobile",
                "client_version": "1.0.0",
            },
        )
        assert result.status_code == 426 and result.json()["status_code"] == 10662
        assert result.json()["data"]["minimum_client_version"] == "1.1.0"
        identity.assert_not_called()


async def test_legacy_login_adapter_retains_pre_cutover_protocol_then_refuses_old_mobile(settings_env, monkeypatch):
    """AC-25/29: The no-Origin old entry works before deployment cutover and returns 426 afterwards."""
    from unittest.mock import AsyncMock, Mock

    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response

    from bisheng.api.services.audit_log import AuditLogService
    from bisheng.common.services.config_service import settings
    from bisheng.user.domain.models.user import UserLogin
    from bisheng.user.domain.schemas.password_identity import PasswordLoginIdentity
    from bisheng.user.domain.services import user as module
    from bisheng.user.domain.services.auth import LoginUser

    person = SimpleNamespace(user_id=7, user_name="unit-platform-auth")
    verified = PasswordLoginIdentity(person, 9, (2,), False, 0)
    monkeypatch.setattr(module.UserService, "authenticate_password", AsyncMock(return_value=verified))
    monkeypatch.setattr(LoginUser, "create_access_token", Mock(return_value="unit-old-protocol-token"))
    monkeypatch.setattr(LoginUser, "set_access_cookies", Mock())
    monkeypatch.setattr(LoginUser, "init_login_user", AsyncMock(return_value=SimpleNamespace(is_global_super=False)))
    monkeypatch.setattr(LoginUser, "user_entry_payload_for_read", AsyncMock(return_value={}))
    monkeypatch.setattr(module.UserService, "build_user_read", AsyncMock(side_effect=lambda user, **kw: kw))
    monkeypatch.setattr(AuditLogService, "user_login", Mock())
    monkeypatch.setattr(module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(module, "get_redis_client", AsyncMock(return_value=SimpleNamespace(aset=AsyncMock())))
    monkeypatch.setattr(settings.multi_tenant, "enabled", False)
    monkeypatch.setattr(settings.platform_auth, "mobile_cutover_ready", False)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("localhost", 7860),
            "client": ("127.0.0.1", 1000),
            "path": "/api/v1/user/login",
            "headers": [],
            "app": FastAPI(),
        }
    )
    auth = SimpleNamespace(res=Response(), cookie_conf=SimpleNamespace(jwt_token_expire_time=86400))
    result = await module.UserService.user_login(
        request, UserLogin(user_name=person.user_name, password="cipher"), auth
    )
    assert result.data["access_token"] == "unit-old-protocol-token"
    monkeypatch.setattr(settings.platform_auth, "mobile_cutover_ready", True)
    with pytest.raises(PlatformAuthError) as caught:
        await module.UserService.user_login(request, UserLogin(user_name=person.user_name, password="cipher"), auth)
    assert caught.value.http_status == 426


async def test_platform_upload_activity_declaration_does_not_change_legacy_dsh_policy(actual_identity_service):
    """AC-07/20: Newly declared upload activity renews platform sessions only."""
    from starlette.requests import Request

    from bisheng.core.session_activity import AuthenticatedActivity, record_authenticated_activity
    from bisheng.user.application.activity_policy import declare_platform_activity
    from bisheng.user.domain.services.platform_identity import PlatformActivity

    service, _ = actual_identity_service
    clock = [datetime(2026, 1, 1)]
    service.now = lambda: clock[0]
    issued = await service.issue(701, 901, "bisheng-mobile")

    def upload_business():
        return None

    declare_platform_activity(SimpleNamespace(routes=[SimpleNamespace(endpoint=upload_business)]), "upload_business")
    clock[0] += timedelta(days=20)
    request = Request({"type": "http", "path": "/unit-platform/upload", "endpoint": upload_business, "headers": []})
    request.state.authenticated_activity = PlatformActivity(service, issued["access_token"])
    await record_authenticated_activity(request)
    assert (await service.inspect(issued["access_token"]))["session_expires_at"] != issued["session_expires_at"]

    class LegacyActivity(AuthenticatedActivity):
        count = 0

        async def record(self):
            self.count += 1

    legacy = LegacyActivity()
    request = Request({"type": "http", "path": "/unit-platform/upload", "endpoint": upload_business, "headers": []})
    request.state.authenticated_activity = legacy
    await record_authenticated_activity(request)
    assert legacy.count == 0


@pytest.mark.parametrize("transport", ["bearer", "selected_cookie"])
@pytest.mark.parametrize("failure", ["expired", "invalid_signature"])
async def test_real_middleware_ignores_unrelated_platform_credentials_on_public_entrances(
    actual_identity_service, transport, failure
):
    """AC-27: Ambient platform credentials cannot block public or independent share-proof handlers."""
    from fastapi import FastAPI, Request
    from httpx import ASGITransport, AsyncClient
    from starlette.responses import JSONResponse

    from bisheng.utils.http_middleware import CustomMiddleware

    service, _ = actual_identity_service
    clock = [datetime(2026, 1, 1)]
    service.now = lambda: clock[0]
    issued = await service.issue(701, 901, "bisheng-web")
    token = issued["access_token"]
    if failure == "expired":
        clock[0] += timedelta(days=31)
    else:
        head, body, signature = token.split(".")
        signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        token = ".".join((head, body, signature))
    app = FastAPI()
    app.state.platform_auth_service = service
    app.add_middleware(CustomMiddleware)
    reached = []

    async def public_handler(request: Request):
        reached.append(request.url.path)
        if (
            request.url.path.startswith("/api/v1/share-link")
            and request.query_params.get("share_token") != "unit-share-proof"
        ):
            return JSONResponse({"own_proof": "required"}, status_code=403)
        return {"own_handler": True}

    for path in ["/api/v1/env", "/api/v1/user/get_captcha", "/api/v1/share-link/unit", "/api/v1/unit-protected"]:
        app.add_api_route(path, public_handler, methods=["GET"])
    headers = (
        {"Authorization": f"Bearer {token}"}
        if transport == "bearer"
        else {"Cookie": f"platform_session_hint={issued['session_id']}; platform_access_{issued['session_id']}={token}"}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        for path in ["/api/v1/env", "/api/v1/user/get_captcha", "/api/v1/share-link/unit?share_token=unit-share-proof"]:
            response = await client.get(path, headers=headers)
            assert response.status_code == 200 and response.json()["own_handler"] is True
        assert reached == ["/api/v1/env", "/api/v1/user/get_captcha", "/api/v1/share-link/unit"]
        denied_share = await client.get("/api/v1/share-link/unit", headers=headers)
        assert denied_share.status_code == 403 and denied_share.json()["own_proof"] == "required"
        denied = await client.get("/api/v1/unit-protected", headers=headers)
        assert denied.status_code == 401
        assert denied.json()["status_code"] == (10651 if failure == "expired" else 10650)
        assert "/api/v1/unit-protected" not in reached


async def test_auth_refresh_keeps_conflict_check_after_middleware_delegates_credential_ownership(
    actual_identity_service,
):
    """AC-27: Auth-owned refresh still rejects Cookie/Bearer conflicts after ambient parsing is skipped."""
    from httpx import ASGITransport, AsyncClient

    from bisheng.utils.http_middleware import CustomMiddleware
    from test.platform_auth.test_platform_api import app_for

    service, _ = actual_identity_service
    selected = await service.issue(701, 901, "bisheng-web")
    other = await service.issue(701, 901, "bisheng-mobile")
    app = app_for(service)
    app.add_middleware(CustomMiddleware)
    sid = selected["session_id"]
    cookie = f"platform_session_hint={sid}; platform_access_{sid}={selected['access_token']}; platform_refresh_{sid}={selected['refresh_token']}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://platform.test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={},
            headers={
                "Cookie": cookie,
                "Authorization": f"Bearer {other['access_token']}",
                "Origin": "https://platform.test",
                "X-CSRF-Token": selected["csrf_token"],
            },
        )
        assert response.status_code == 400 and response.json()["status_code"] == 10661
    await service.inspect(selected["access_token"])
    await service.inspect(other["access_token"])

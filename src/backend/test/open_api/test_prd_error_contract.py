"""Exercise the PRD's code/status pairs through the shipped v2 routes."""

import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.errcode import open_api as errors
from bisheng.common.errcode.assistant import AssistantNotExistsError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionServiceUnavailableError
from bisheng.database.models.session import MessageSession
from bisheng.main import _EXCEPTION_HANDLERS
from bisheng.main import app as production_app
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.services.credential_service import hash_token
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal
from test.open_api.test_dependencies import natural_person_principal, service_account_principal

V2_HTTP_ROUTES = [
    (method, route.path)
    for route in production_app.routes
    if isinstance(route, APIRoute) and route.path.startswith("/api/v2/")
    for method in sorted(route.methods)
]
V2_WS_ROUTES = [
    route.path
    for route in production_app.routes
    if isinstance(route, APIWebSocketRoute) and route.path.startswith("/api/v2/")
]
PRD_ERRORS = [
    (errors.OpenApiCredentialMissingError, 26001, 401),
    (errors.OpenApiCredentialInvalidError, 26002, 401),
    (errors.OpenApiScopeMissingError, 26003, 403),
    (errors.OpenApiDelegationNotAllowedError, 26004, 403),
    (errors.OpenApiDelegationTargetInvalidError, 26005, 403),
    (errors.OpenApiDelegationModeUnsupportedError, 26006, 403),
    (errors.OpenApiPrivilegedTargetError, 26007, 403),
    (errors.OpenApiIdentityHeaderConflictError, 26010, 400),
    (errors.OpenApiAsyncUnsupportedError, 26015, 400),
    (errors.OpenApiDelegationHeaderRequiredError, 26016, 400),
    (errors.OpenApiTaskModeUnsupportedError, 26017, 400),
    (errors.PersonalTokenDisabledError, 26040, 403),
    (errors.PersonalTokenScopeInvalidError, 26041, 400),
    (errors.PersonalTokenTtlExceededError, 26042, 400),
    (errors.PersonalTokenHolderInvalidError, 26043, 401),
]
RESOURCE_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def rpc_app(monkeypatch):
    # Keep the production router and middleware; external audit writes are not
    # part of this transport contract test, and no lifespan is started.
    monkeypatch.setattr("bisheng.open_api.api.middleware.open_api_call_audit_service.enqueue", lambda _entry: True)
    monkeypatch.setitem(production_app.dependency_overrides, get_db_session, lambda: None)
    return production_app


@pytest.fixture
def authenticated(monkeypatch):
    principal = service_account_principal(
        scopes=frozenset({"knowledge:read", "knowledge:write", "assistant:invoke", "workflow:invoke", "chat:invoke"})
    )
    validate = AsyncMock(return_value=principal)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)
    owner = SimpleNamespace(user_id=12, user_name="owner", delete=0)
    monkeypatch.setattr("bisheng.open_endpoints.domain.utils.UserDao.get_user", Mock(return_value=owner))
    monkeypatch.setattr("bisheng.open_endpoints.domain.utils.UserDao.aget_user", AsyncMock(return_value=owner))
    monkeypatch.setattr("bisheng.open_endpoints.domain.utils._get_active_tenant_id_sync", Mock(return_value=9))
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.utils.UserTenantDao.aget_active_user_tenant",
        AsyncMock(return_value=SimpleNamespace(tenant_id=9)),
    )
    monkeypatch.setattr("bisheng.open_api.api.endpoints.auth.CredentialRepository.get", AsyncMock(return_value=None))
    return validate


async def send(app, method, path, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.parametrize(("method", "path"), V2_HTTP_ROUTES)
@pytest.mark.parametrize("authorization", [None, "Bearer jwt.header.payload"])
async def test_every_http_route_authenticates_before_body_validation(rpc_app, method, path, authorization):
    headers = {"Content-Type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    response = await send(rpc_app, method, re.sub(r"\{[^}]+\}", "1", path), headers=headers, content=b"{")
    assert response.status_code == 401, response.text
    assert response.json()["status_code"] == 26001


@pytest.mark.parametrize(("error_type", "code", "http_status"), PRD_ERRORS)
@pytest.mark.parametrize("legacy_http_exception", [False, True])
async def test_prd_errors_have_the_same_status_through_both_exception_paths(
    error_type, code, http_status, legacy_http_exception
):
    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    register_open_api_exception_handlers(app)

    @app.get("/api/v2/error")
    @app.get("/api/v1/error")
    async def fail():
        if legacy_http_exception:
            raise error_type.http_exception()
        kwargs = {"required": "knowledge:read"} if code == 26003 else {}
        raise error_type(**kwargs)

    response = await send(app, "GET", "/api/v2/error")
    assert (response.status_code, response.json()["status_code"]) == (http_status, code)
    legacy = await send(app, "GET", "/api/v1/error")
    assert (legacy.status_code, legacy.json()["status_code"]) == (200, code)


@pytest.mark.parametrize("path", V2_WS_ROUTES)
@pytest.mark.parametrize(("authorization", "code"), [(None, 26001), ("Bearer jwt.header.payload", 26001)])
def test_each_websocket_rejects_before_accept(rpc_app, path, authorization, code):
    from starlette.websockets import WebSocketDisconnect

    headers = {} if authorization is None else {"Authorization": authorization}
    client = TestClient(rpc_app)
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(re.sub(r"\{[^}]+\}", RESOURCE_ID, path), headers=headers):
            pytest.fail("Unauthenticated websocket was accepted")
    assert (caught.value.code, caught.value.reason) == (1008, str(code))


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"task_mode": True}, 26017),
        ({"run_mode": "task"}, 26017),
        ({"run_mode": "unknown"}, 26017),
        ({"run_mode": None}, 26017),
        ({"execution": "async"}, 26015),
        ({"background": True}, 26015),
        ({"task_mode": True, "background": True}, 26017),
    ],
)
async def test_daily_unavailable_modes_keep_prd_codes(rpc_app, authenticated, extra, code):
    response = await send(
        rpc_app,
        "POST",
        "/api/v2/workstation/chat/completions",
        json={"clientTimestamp": "1", "model": "m", **extra},
    )
    assert (response.status_code, response.json()["status_code"]) == (400, code)
    authenticated.assert_awaited_once()
    assert get_current_open_api_principal() is None


async def test_daily_intent_fields_do_not_relabel_other_endpoint_validation(rpc_app, authenticated):
    response = await send(rpc_app, "POST", "/api/v2/workflow/invoke", json={"task_mode": True})
    assert (response.status_code, response.json()["status_code"]) == (400, 400)


@pytest.mark.parametrize("target", ["-1", "0", "x", "2147483648", "9" * 5000])
async def test_invalid_delegation_targets_are_403_not_server_errors(rpc_app, authenticated, target):
    authenticated.return_value = authenticated.return_value.model_copy(
        update={"scopes": frozenset({"knowledge:read", "delegate"})}
    )
    response = await send(rpc_app, "GET", "/api/v2/auth/whoami", headers={"X-On-Behalf-Of": target})
    assert (response.status_code, response.json()["status_code"]) == (403, 26005)


@pytest.mark.parametrize(
    ("error_type", "http_status"),
    [
        (UnAuthorizedError, 403),
        (PermissionDeniedError, 403),
        (AssistantNotExistsError, 404),
        (PermissionServiceUnavailableError, 503),
        (errors.OpenApiScopeMissingError, 403),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
async def test_assistant_setup_preserves_business_errors(
    rpc_app, authenticated, monkeypatch, error_type, http_status, stream
):
    kwargs = {"required": "assistant:invoke"} if error_type is errors.OpenApiScopeMissingError else {}
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.assistant.PublishedAssistantService.complete",
        AsyncMock(side_effect=error_type(**kwargs)),
    )
    response = await send(
        rpc_app,
        "POST",
        "/api/v2/assistant/chat/completions",
        json={
            "model": RESOURCE_ID,
            "messages": [],
            "stream": stream,
        },
    )
    assert (response.status_code, response.json()["status_code"]) == (http_status, error_type.Code)


async def test_legacy_filelib_error_does_not_become_a_five_digit_http_status(rpc_app, authenticated, monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.filelib.KnowledgeService.get_knowledge",
        AsyncMock(side_effect=KnowledgeTypeNotSupportedError.http_exception()),
    )
    response = await send(rpc_app, "GET", "/api/v2/filelib/", params={"type": 99})
    assert (response.status_code, response.json()["status_code"]) == (400, 10962)


@pytest.mark.parametrize("valid_key", [False, True])
async def test_stale_login_cookie_cannot_override_v2_authentication(rpc_app, authenticated, monkeypatch, valid_key):
    decode = Mock(side_effect=AssertionError("V2 must not decode login JWTs"))
    monkeypatch.setattr("bisheng.utils.http_middleware._decode_jwt_subject", decode)
    if not valid_key:
        authenticated.side_effect = errors.OpenApiCredentialMissingError()
    response = await send(rpc_app, "GET", "/api/v2/auth/whoami", headers={"Cookie": "access_token_cookie=stale-login"})
    assert response.status_code == (200 if valid_key else 401), response.text
    if not valid_key:
        assert response.json()["status_code"] == 26001
    decode.assert_not_called()


@pytest.mark.parametrize(
    ("reason", "subject_kind", "code"),
    [
        ("manual", "service_account", 26002),
        ("manual", "natural_person", 26002),
        ("subject_disabled", "service_account", 26027),
        ("subject_deleted", "service_account", 26027),
        ("subject_disabled", "natural_person", 26043),
        ("subject_deleted", "natural_person", 26043),
        (None, "service_account", 26002),
        (None, "natural_person", 26002),
    ],
)
async def test_revocation_reason_and_expiry_preserve_prd_identity_errors(
    rpc_app, fake_redis, monkeypatch, reason, subject_kind, code
):
    prefix = "bs-sak-" if subject_kind == "service_account" else "bs-pat-"
    plaintext = prefix + "a" * 43
    row = ApiCredential(
        id=1,
        tenant_id=1,
        subject_kind=subject_kind,
        subject_id=1,
        name="test",
        key_prefix=prefix,
        last4="aaaa",
        token_hash=hash_token(plaintext),
        revoked_at=datetime.now() if reason else None,
        revoke_reason=reason,
        expires_at=datetime.now() - timedelta(seconds=1),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.credential_validator.CredentialRepository.get_by_hash",
        AsyncMock(return_value=row),
    )
    response = await send(rpc_app, "GET", "/api/v2/auth/whoami", headers={"Authorization": f"Bearer {plaintext}"})
    assert (response.status_code, response.json()["status_code"]) == (401, code)


@pytest.mark.parametrize("deployment_enabled", [False, True])
async def test_pat_disabled_at_either_gate_is_403(rpc_app, authenticated, monkeypatch, deployment_enabled):
    authenticated.return_value = natural_person_principal()
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", deployment_enabled)
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.TenantSettingService.get_policy",
        AsyncMock(return_value=SimpleNamespace(enabled=False)),
    )
    response = await send(rpc_app, "GET", "/api/v2/auth/whoami")
    assert (response.status_code, response.json()["status_code"]) == (403, 26040)


async def test_foreign_session_stop_is_403_while_read_is_404(rpc_app, authenticated, monkeypatch):
    foreign = authenticated.return_value.model_copy(update={"actor_id": 999, "authorization_subject_id": 999})
    row = session_subject_from_principal(foreign).stamp(
        MessageSession(
            chat_id="foreign",
            flow_id=RESOURCE_ID.replace("-", ""),
            flow_type=10,
            user_id=12,
            tenant_id=9,
        )
    )
    monkeypatch.setattr("bisheng.chat_session.domain.chat.MessageSessionDao.async_get_one", AsyncMock(return_value=row))
    stop_callback = AsyncMock()
    monkeypatch.setattr("bisheng.workflow.domain.services.published_workflow_service.RedisCallback", stop_callback)
    response = await send(
        rpc_app,
        "POST",
        "/api/v2/workflow/stop",
        json={"workflow_id": RESOURCE_ID, "session_id": "foreign_async_task_id"},
    )
    assert (response.status_code, response.json()["status_code"]) == (403, 403)
    stop_callback.assert_not_called()
    response = await send(rpc_app, "GET", "/api/v2/chat/info", params={"chat_id": "foreign"})
    assert (response.status_code, response.json()["status_code"]) == (404, 404)


@pytest.mark.parametrize(
    ("error_type", "http_status"),
    [
        (UnAuthorizedError, 403),
        (PermissionDeniedError, 403),
        (PermissionServiceUnavailableError, 503),
        (errors.OpenApiCredentialInvalidError, 401),
    ],
)
async def test_daily_setup_errors_are_reported_before_sse(rpc_app, authenticated, monkeypatch, error_type, http_status):
    async def prepare_request(*, principal, request, login_user):
        return request.to_internal(), session_subject_from_principal(principal)

    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.workstation.OpenDailyChatService.prepare_request", prepare_request
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service._agent_initialize_chat", AsyncMock(side_effect=error_type())
    )
    response = await send(
        rpc_app, "POST", "/api/v2/workstation/chat/completions", json={"model": "m", "clientTimestamp": "1"}
    )
    assert (response.status_code, response.json()["status_code"]) == (http_status, error_type.Code)
    assert response.headers["content-type"] == "application/json"


async def test_v1_daily_setup_keeps_its_sse_contract(monkeypatch):
    from starlette.requests import Request

    from bisheng.workstation.domain.schemas.chat import APIChatCompletion
    from bisheng.workstation.domain.services.chat_service import stream_chat_completion

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.chat_service._agent_initialize_chat",
        AsyncMock(side_effect=PermissionDeniedError()),
    )
    response = await stream_chat_completion(
        Request({"type": "http", "path": "/api/v1/workstation/chat/completions"}),
        APIChatCompletion(model="m", clientTimestamp="1"),
        SimpleNamespace(user_id=12),
    )
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    content = "".join([part async for part in response.body_iterator])
    assert str(PermissionDeniedError.Code) in content


@pytest.mark.parametrize(
    ("headers", "delegate", "privileged", "allowed", "target_tenant", "code", "http_status"),
    [
        ({"X-On-Behalf-Of": "21"}, False, False, True, 9, 26004, 403),
        ({"X-On-Behalf-Of": "invalid"}, False, False, True, 9, 26004, 403),
        ({"X-On-Behalf-Of": "21"}, True, False, True, None, 26005, 403),
        ({"X-On-Behalf-Of": "21"}, True, False, True, 10, 26005, 403),
        ({"X-On-Behalf-Of": "21"}, True, True, True, 9, 26007, 403),
        ({"X-On-Behalf-Of": "21"}, True, False, False, 9, 26004, 403),
        ({"X-On-Behalf-Of": "21", "X-End-User": "u"}, True, False, True, 9, 26010, 400),
        ({}, True, False, True, 9, 26016, 400),
    ],
)
async def test_identity_gate_error_pairs(
    rpc_app, authenticated, monkeypatch, headers, delegate, privileged, allowed, target_tenant, code, http_status
):
    if delegate:
        authenticated.return_value = authenticated.return_value.model_copy(
            update={"scopes": frozenset({"knowledge:read", "delegate"})}
        )
    target = SimpleNamespace(user_id=21, tenant_id=target_tenant) if target_tenant else None
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.OwnerRepository.get_active_natural_person",
        AsyncMock(return_value=target),
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service._is_privileged_target", AsyncMock(return_value=privileged)
    )
    monkeypatch.setattr(
        "bisheng.open_api.domain.services.identity_service.DelegateScopeService.target_allowed",
        AsyncMock(return_value=allowed),
    )
    response = await send(rpc_app, "GET", "/api/v2/auth/whoami", headers=headers)
    assert (response.status_code, response.json()["status_code"]) == (http_status, code)

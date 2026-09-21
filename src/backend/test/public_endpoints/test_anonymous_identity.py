"""Caller credentials never select an identity or deny an anonymous v3 request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.assistant import AssistantStatus
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.database.models.session import MessageSessionDao
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.api.endpoints import assistant, flow, workflow
from bisheng.public_endpoints.api.exception_handlers import register_public_exception_handlers
from bisheng.public_endpoints.api.router import router_public
from bisheng.public_endpoints.domain.services import guest_policy
from bisheng.utils import http_middleware

WORKFLOW_ID = UUID(int=301).hex
ASSISTANT_ID = UUID(int=302).hex
CALLER_HEADERS = [
    {},
    {"Authorization": "Bearer invalid-token"},
    {"Authorization": "Bearer bs-sak-" + "a" * 43},
    {"Authorization": "Bearer bs-pat-" + "b" * 43},
    {"Cookie": "access_token_cookie=stale-login-token"},
    {"X-On-Behalf-Of": "999"},
    {"X-On-Behalf-Of": ""},
    {"X-End-User": "another-user"},
    {"X-API-Key": "invalid-key", "X-User-Id": "999"},
    {
        "Authorization": "Bearer ignored-token",
        "Cookie": "access_token_cookie=ignored-cookie",
        "X-On-Behalf-Of": "999",
        "X-End-User": "another-user",
    },
]
IGNORED_QUERY = "token=ignored&api_key=ignored&user_id=999&X-On-Behalf-Of=999&X-End-User=another-user"


class PublicIdentity(BaseModel):
    operator_user_id: int
    tenant_id: int
    actor_user_id: int
    can_share: bool = False


def _identity(operator):
    return PublicIdentity(
        operator_user_id=operator.user_id,
        tenant_id=get_current_tenant_id(),
        actor_user_id=get_current_permission_actor().subject_id,
    )


@pytest.fixture
def publication(monkeypatch):
    state = SimpleNamespace(
        workflow=SimpleNamespace(tenant_id=3, flow_type=FlowType.WORKFLOW.value, status=FlowStatus.ONLINE.value),
        assistant=SimpleNamespace(tenant_id=3, is_delete=False, status=AssistantStatus.ONLINE.value),
    )
    monkeypatch.setattr(
        guest_policy.FlowDao,
        "aget_flow_by_id",
        AsyncMock(side_effect=lambda resource_id: state.workflow if resource_id == WORKFLOW_ID else None),
    )
    monkeypatch.setattr(
        guest_policy.AssistantDao,
        "aget_one_assistant",
        AsyncMock(side_effect=lambda resource_id: state.assistant if resource_id == ASSISTANT_ID else None),
    )
    monkeypatch.setattr(
        guest_policy,
        "_load_default_operator",
        AsyncMock(return_value=SimpleNamespace(user_id=41, user_name="operator", tenant_id=3, is_global_super=False)),
    )
    monkeypatch.setattr("bisheng.permission.application.relation_api.is_tenant_admin", AsyncMock(return_value=False))
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(return_value=None))

    async def flow_info(operator, _resource_id):
        return resp_200(data=_identity(operator).model_dump())

    async def assistant_info(_resource_id, operator):
        return _identity(operator)

    async def dispatch(websocket, _resource_id, _chat_id, operator, _work_type, _request, **kwargs):
        identity = _identity(operator).model_dump()
        subject = kwargs["session_subject"]
        assert subject.subject_type == "public_v3"
        assert subject.tenant_id == 3
        snapshot = kwargs.get("execution_snapshot")
        if snapshot is not None:
            assert snapshot["effective_user_id"] == 41
            assert snapshot["credential_id"] is None
        await websocket.accept()
        await websocket.send_json(identity)
        await websocket.close()

    monkeypatch.setattr(flow.FlowService, "get_one_flow", flow_info)
    monkeypatch.setattr(assistant.PublishedAssistantService, "get_info", assistant_info)
    monkeypatch.setattr(workflow.chat_manager, "dispatch_client", dispatch)
    state.decode = Mock(side_effect=AssertionError("v3 must not decode caller JWTs"))
    monkeypatch.setattr(http_middleware, "_decode_jwt_subject", state.decode)
    return state


@pytest.fixture
def client(publication):
    app = FastAPI()
    app.include_router(router_public)
    register_public_exception_handlers(app)
    register_open_api_exception_handlers(app)
    app.add_middleware(http_middleware.CustomMiddleware)
    app.add_middleware(http_middleware.WebSocketLoggingMiddleware)

    for path in ("/api/v1/probe", "/api/v30/probe"):
        app.add_api_route(path, lambda: {"ok": True})

    rpc = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @rpc.get("/probe")
    @open_api_scope(None)
    async def probe():
        pytest.fail("A request without an API credential cannot enter v2 business code")

    app.include_router(rpc)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("headers", CALLER_HEADERS)
@pytest.mark.parametrize("path", [f"/flows/{WORKFLOW_ID}", f"/assistant/info/{ASSISTANT_ID}"])
def test_http_credentials_and_identity_parameters_are_ignored(client, publication, path, headers):
    response = client.get(f"/api/v3{path}?{IGNORED_QUERY}", headers=headers)

    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"] == {
        "operator_user_id": 41,
        "tenant_id": 3,
        "actor_user_id": 41,
        "can_share": False,
    }
    publication.decode.assert_not_called()


@pytest.mark.parametrize("headers", CALLER_HEADERS)
@pytest.mark.parametrize("path", [f"/workflow/chat/{WORKFLOW_ID}", f"/assistant/chat/{ASSISTANT_ID}"])
def test_websocket_credentials_and_identity_parameters_are_ignored(client, publication, path, headers):
    with client.websocket_connect(f"/api/v3{path}?chat_id=draft&{IGNORED_QUERY}", headers=headers) as websocket:
        assert websocket.receive_json() == {
            "operator_user_id": 41,
            "tenant_id": 3,
            "actor_user_id": 41,
            "can_share": False,
        }
    publication.decode.assert_not_called()


def test_ignored_credentials_do_not_override_publication_denial(client, publication):
    publication.workflow.status = FlowStatus.OFFLINE.value

    response = client.get(f"/api/v3/flows/{WORKFLOW_ID}", headers=CALLER_HEADERS[-1])

    assert response.status_code == 404
    assert response.json()["status_code"] == 26102
    publication.decode.assert_not_called()


@pytest.mark.parametrize("path", ["/api/v1/probe", "/api/v30/probe"])
@pytest.mark.parametrize("header", ["Authorization", "Cookie"])
def test_login_token_revocation_remains_enforced_outside_v3(client, publication, monkeypatch, path, header):
    publication.decode.side_effect = None
    publication.decode.return_value = {"user_id": 99, "tenant_id": 9, "token_version": 1}
    monkeypatch.setattr(http_middleware, "_validate_token_version", AsyncMock(return_value=False))
    value = "Bearer revoked-token" if header == "Authorization" else "access_token_cookie=revoked-token"

    response = client.get(path, headers={header: value})

    assert response.status_code == 401
    assert response.json()["status_code"] == 19103
    publication.decode.assert_called_once()


def test_v2_still_requires_an_api_key_even_with_browser_cookie_and_identity_headers(client, publication):
    response = client.get("/api/v2/probe", headers={"Cookie": "access_token_cookie=ignored", "X-On-Behalf-Of": "41"})

    assert response.status_code == 401
    assert response.json()["status_code"] == 26001
    publication.decode.assert_not_called()

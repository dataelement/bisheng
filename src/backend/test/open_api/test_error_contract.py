"""HTTP-level regressions for the PRD appendix C and admission order."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, field_validator

from bisheng.common.errcode import open_api
from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionCheckFailedError,
    PermissionDeniedError,
    PermissionEnumerationIncompleteError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.scopes import open_api_scope
from test.open_api.test_dependencies import natural_person_principal, service_account_principal

# Literal expectations come from PRD appendix C, not production http_status.
PRD_ERRORS = [
    (open_api.OpenApiCredentialMissingError(), 26001, 401),
    (open_api.OpenApiCredentialInvalidError(), 26002, 401),
    (open_api.OpenApiScopeMissingError(required="knowledge:read"), 26003, 403),
    (open_api.OpenApiDelegationNotAllowedError(), 26004, 403),
    (open_api.OpenApiDelegationTargetInvalidError(), 26005, 403),
    (open_api.OpenApiDelegationModeUnsupportedError(), 26006, 403),
    (open_api.OpenApiPrivilegedTargetError(), 26007, 403),
    (open_api.OpenApiIdentityHeaderConflictError(), 26010, 400),
    (open_api.OpenApiAsyncUnsupportedError(), 26015, 400),
    (open_api.OpenApiDelegationHeaderRequiredError(), 26016, 400),
    (open_api.OpenApiTaskModeUnsupportedError(), 26017, 400),
    (open_api.OpenApiEndUserInvalidError(), 26018, 400),
    (open_api.OpenApiRemovedIdentityInputError(), 26019, 400),
    (open_api.PersonalTokenDisabledError(), 26040, 403),
    (open_api.PersonalTokenScopeInvalidError(), 26041, 400),
    (open_api.PersonalTokenTtlExceededError(), 26042, 400),
    (open_api.PersonalTokenHolderInvalidError(), 26043, 401),
    (open_api.PersonalTokenDataScopeError(), 26044, 403),
]


class BodyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str

    @field_validator("text")
    @classmethod
    def reject_empty(cls, value):
        if not value:
            raise ValueError("text cannot be empty")
        return value


@pytest.fixture
def contract_app(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    app = FastAPI()
    register_open_api_exception_handlers(app)
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])

    @router.post("/body")
    @router.post("/workstation/chat/completions")
    @open_api_scope("knowledge:read")
    async def body(payload: BodyPayload):
        return payload

    @router.post("/upload")
    @open_api_scope("knowledge:read")
    async def upload(file: UploadFile = File(...)):
        return {"filename": file.filename}

    app.include_router(router)
    return app


@pytest.mark.parametrize("error,code,http_status", PRD_ERRORS)
@pytest.mark.parametrize("legacy_http_error", [False, True])
async def test_prd_error_codes_and_transport_statuses(contract_app, error, code, http_status, legacy_http_error):
    @contract_app.get("/api/v2/failure", dependencies=[Depends(verify_open_api_access)])
    @open_api_scope("knowledge:read")
    async def failure():
        raise type(error).http_exception() if legacy_http_error else error

    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.get("/api/v2/failure")
    assert response.status_code == http_status
    assert response.json()["status_code"] == code


@pytest.mark.parametrize(
    "error",
    [
        PermissionCheckFailedError(),
        PermissionServiceUnavailableError(),
        PermissionEnumerationIncompleteError(),
        PermissionProjectionFailedError(),
        PermissionPublishNotReadyError(),
        AuthorizationModelMismatchError(),
    ],
)
@pytest.mark.parametrize("legacy_http_error", [False, True])
async def test_permission_evaluation_failure_is_5xx(contract_app, error, legacy_http_error):
    @contract_app.get("/api/v2/failure", dependencies=[Depends(verify_open_api_access)])
    @open_api_scope("knowledge:read")
    async def failure():
        raise type(error).http_exception() if legacy_http_error else error

    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.get("/api/v2/failure")
    assert response.status_code == 503
    assert response.json()["status_code"] == error.code


@pytest.mark.parametrize("error,http_status", [(KnowledgeTypeNotSupportedError(), 400), (PermissionDeniedError(), 403)])
async def test_legacy_business_http_exception_keeps_business_code(contract_app, error, http_status):
    @contract_app.get("/api/v2/failure", dependencies=[Depends(verify_open_api_access)])
    @open_api_scope("knowledge:read")
    async def failure():
        raise type(error).http_exception()

    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.get("/api/v2/failure")
    assert response.status_code == http_status
    assert response.json()["status_code"] == error.code


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"task_mode": True}, 26017),
        ({"run_mode": "task"}, 26017),
        ({"run_mode": "unknown"}, 26017),
        ({"execution": "async"}, 26015),
        ({"background": True}, 26015),
        ({"task_mode": True, "background": True}, 26017),
        ({"text": ""}, 400),
    ],
)
async def test_daily_chat_capability_errors_are_scoped_to_daily_chat(contract_app, payload, code):
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        daily = await client.post("/api/v2/workstation/chat/completions", json=payload)
        other = await client.post("/api/v2/body", json=payload)
    assert (daily.status_code, daily.json()["status_code"]) == (400, code)
    assert (other.status_code, other.json()["status_code"]) == (400, 400)


@pytest.mark.parametrize(
    "path,content_type,body",
    [
        ("/body", "application/json", b"{"),
        ("/body", "application/json", b'"\xff"'),
        ("/upload", "multipart/form-data", b"malformed form"),
    ],
)
@pytest.mark.parametrize("code,http_status", [(26001, 401), (26002, 401), (26030, 503), (None, 400)])
async def test_credential_checks_precede_body_parser_errors(
    contract_app, monkeypatch, path, content_type, body, code, http_status
):
    errors = {
        26001: open_api.OpenApiCredentialMissingError,
        26002: open_api.OpenApiCredentialInvalidError,
        26030: open_api.OpenApiAuthDependencyUnavailableError,
    }
    if code is not None:
        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", AsyncMock(side_effect=errors[code]()))
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.post("/api/v2" + path, content=body, headers={"Content-Type": content_type})
    assert response.status_code == http_status
    assert response.json()["status_code"] == (code or 400)


@pytest.mark.parametrize(
    "content_type", [None, "application/json", "application/problem+json", "Application/JSON; charset=utf-8"]
)
async def test_removed_user_id_is_rejected_for_all_json_media_types(contract_app, content_type):
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.post(
            "/api/v2/body",
            content=json.dumps({"text": "query", "user_id": 1}),
            headers={"Content-Type": content_type} if content_type else {},
        )
    assert (response.status_code, response.json()["status_code"]) == (400, 26019)


@pytest.mark.parametrize("target", ["9" * 5000, str(2**63)])
async def test_out_of_range_delegate_id_has_same_error_as_missing_target(contract_app, monkeypatch, target):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal(scopes=frozenset({"knowledge:read", "delegate"}))),
    )
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.post("/api/v2/body", json={"text": "query"}, headers={"X-On-Behalf-Of": target})
    assert (response.status_code, response.json()["status_code"]) == (403, 26005)


@pytest.mark.parametrize("deployment_enabled,tenant_enabled", [(False, True), (True, False)])
async def test_pat_disabled_gates_return_26040(contract_app, monkeypatch, deployment_enabled, tenant_enabled):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer", AsyncMock(return_value=natural_person_principal())
    )
    monkeypatch.setattr("bisheng.open_api.api.dependencies.settings.open_api.pat_enabled", deployment_enabled)
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.TenantSettingService.get_policy",
        AsyncMock(return_value=SimpleNamespace(enabled=tenant_enabled, data_scope="all_visible")),
    )
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.post("/api/v2/body", json={"text": "query"})
    assert (response.status_code, response.json()["status_code"]) == (403, 26040)


async def test_v1_handlers_and_non_v2_paths_keep_existing_contract():
    from bisheng.main import _EXCEPTION_HANDLERS

    app = FastAPI(exception_handlers=_EXCEPTION_HANDLERS)
    register_open_api_exception_handlers(app)

    @app.get("/api/v1/failure")
    @app.get("/api/v20/failure")
    async def failure():
        raise KnowledgeTypeNotSupportedError.http_exception()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/v1/failure", "/api/v20/failure"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json()["status_code"] == KnowledgeTypeNotSupportedError.Code


@pytest.mark.parametrize(
    "headers,code,http_status",
    [
        ({"X-On-Behalf-Of": "7", "X-End-User": "external"}, 26010, 400),
        ({"X-End-User": ""}, 26018, 400),
        ({"X-End-User": "a" * 129}, 26018, 400),
        ({"X-End-User": "tab\tvalue"}, 26018, 400),
        ({"X-Bisheng-End-User": "external"}, 26019, 400),
        ({"X-Custom-On-Behalf-Of": "7"}, 26019, 400),
        ({"X-On-Behalf-Of": "username"}, 26005, 403),
        ({"X-On-Behalf-Of": "7"}, 26004, 403),
    ],
)
async def test_identity_header_failures_return_prd_pairs(contract_app, headers, code, http_status):
    async with AsyncClient(transport=ASGITransport(app=contract_app), base_url="http://test") as client:
        response = await client.post("/api/v2/body", json={"text": "query"}, headers=headers)
    assert (response.status_code, response.json()["status_code"]) == (http_status, code)

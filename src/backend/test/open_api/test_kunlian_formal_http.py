"""Formal router ASGI contracts; no lifespan, broker or external services."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.flow import VersionNameExistsError
from bisheng.common.schemas.api import resp_200
from bisheng.open_endpoints.api.endpoints import kunlian_workflow_api as routes
from bisheng.workflow.application.kunlian_workflow_authorization import GrantReceiptResult


@pytest.fixture
def formal_app(monkeypatch):
    app = FastAPI()
    capabilities = []

    class Access:
        @asynccontextmanager
        async def use_user(self, authorization, user_account, *, capability):
            assert (authorization, user_account) == ("Bearer synthetic", "account-a")
            capabilities.append(capability)
            yield SimpleNamespace(
                user=SimpleNamespace(user_id=17, tenant_id=7), credential=SimpleNamespace(integration_id="partner")
            )

    app.state.kunlian_access_service = Access()
    app.state.kunlian_request_limiter = AsyncMock(return_value=None)
    app.state.kunlian_audit_service = SimpleNamespace(
        begin=AsyncMock(return_value=1), finish=AsyncMock(return_value=True)
    )
    management = SimpleNamespace(
        detail=AsyncMock(return_value=resp_200({"id": "flow", "name": "read"})),
        describe=AsyncMock(
            return_value={
                "workflow_id": "flow",
                "workflow_version_id": "3",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ),
        create=AsyncMock(return_value={"id": "new", "version_id": 1}),
        save_version=AsyncMock(return_value={"id": 3, "draft_revision": "new-revision", "data": {"nodes": []}}),
        create_version=AsyncMock(return_value=VersionNameExistsError.return_resp()),
    )
    app.state.kunlian_workflow_api = management
    permission = SimpleNamespace(change=AsyncMock(return_value=GrantReceiptResult("PENDING")))
    monkeypatch.setattr(routes, "permission_api", AsyncMock(return_value=permission))
    app.include_router(routes.router)
    return app, management, capabilities


async def test_runtime_query_never_returns_arbitrary_failure_text(formal_app, monkeypatch):
    app, _, _ = formal_app
    row = SimpleNamespace(session_id="a" * 32, workflow_version_id=3, status="FAILED", error="private-driver-message")
    monkeypatch.setattr(routes, "run_subject_from_request", lambda access: object())
    monkeypatch.setattr(
        routes,
        "get_kunlian_runtime_service",
        AsyncMock(return_value=SimpleNamespace(query=AsyncMock(return_value=row))),
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v2/kunlian/workflow-runs/" + row.session_id, params=PARAMS, headers=HEADERS)
    assert response.json()["data"]["error"] == "EXECUTION_FAILED"


@pytest.mark.parametrize(
    "status, expected",
    [("CANCEL_REQUESTED", "ACCEPTED"), ("CANCELLED", "CONFIRMED"), ("SUCCEEDED", "ALREADY_TERMINAL")],
)
async def test_cancel_returns_explicit_receipt_state(formal_app, monkeypatch, status, expected):
    app, _, _ = formal_app
    row = SimpleNamespace(session_id="a" * 32, status=status)
    monkeypatch.setattr(routes, "run_subject_from_request", lambda access: object())
    monkeypatch.setattr(
        routes,
        "get_kunlian_runtime_service",
        AsyncMock(return_value=SimpleNamespace(cancel=AsyncMock(return_value=row))),
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/v2/kunlian/workflow-runs/" + row.session_id + "/cancel", params=PARAMS, headers=HEADERS
        )
    assert response.json()["data"]["cancel_state"] == expected


PARAMS = {"user_account": "account-a"}
HEADERS = {"Authorization": "Bearer synthetic", "Idempotency-Key": "request-1", "If-Match": "old-revision"}


async def test_formal_read_and_create_use_declared_capability(formal_app):
    app, management, capabilities = formal_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v2/kunlian/workflows/flow", params=PARAMS, headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["data"]["id"] == "flow"
        response = await client.post("/api/v2/kunlian/workflows", params=PARAMS, headers=HEADERS, json={"name": "new"})
        assert response.status_code == 201
        assert response.json()["data"]["id"] == "new"
    assert capabilities == ["read", "write"]
    management.create.assert_awaited_once()


async def test_formal_schema_is_read_only_and_returns_published_contract(formal_app):
    app, management, capabilities = formal_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/kunlian/workflows/flow/schema", params=PARAMS | {"workflow_version_id": "3"}, headers=HEADERS
        )
    assert response.status_code == 200
    assert response.json()["data"]["workflow_version_id"] == "3"
    assert "data" not in response.json()["data"]
    assert capabilities == ["read"]
    assert management.describe.await_args.kwargs == {"version_id": 3}


async def test_formal_save_has_single_standard_envelope(formal_app):
    app, _, _ = formal_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.put(
            "/api/v2/kunlian/workflows/flow/versions/3",
            params=PARAMS,
            headers=HEADERS,
            json={"name": "v1", "data": {"nodes": []}},
        )
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    assert response.json()["data"]["draft_revision"] == "new-revision"


@pytest.mark.parametrize("receipt_status,http_status", [("PENDING", 202), ("APPLIED", 200)])
@pytest.mark.parametrize("operation", ["grant", "revoke"])
async def test_formal_grant_pending_is_http_202(formal_app, monkeypatch, receipt_status, http_status, operation):
    app, _, _ = formal_app
    monkeypatch.setattr(
        routes,
        "permission_api",
        AsyncMock(return_value=SimpleNamespace(change=AsyncMock(return_value=GrantReceiptResult(receipt_status)))),
    )
    body = {"expected_resource_version": 0, "expected_catalog_release_id": 1}
    if operation == "grant":
        body.update(subject_ref="member", model_key="viewer")
    else:
        body["expected_assignee_version"] = 0
    path = "/api/v2/kunlian/workflows/flow/permissions/grants" + ("/123/revoke" if operation == "revoke" else "")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            path,
            params=PARAMS,
            headers=HEADERS,
            json=body,
        )
    assert response.status_code == http_status
    assert response.json()["data"]["status"] == receipt_status


@pytest.mark.parametrize("assignee_id", ["abc", "0", "-1", "01", "9" * 20])
async def test_formal_revoke_rejects_invalid_assignee_before_business(formal_app, assignee_id):
    app, _, _ = formal_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v2/kunlian/workflows/flow/permissions/grants/{assignee_id}/revoke",
            params=PARAMS,
            headers=HEADERS,
            json={"expected_resource_version": 0, "expected_catalog_release_id": 1, "expected_assignee_version": 0},
        )
    assert response.status_code == 422


async def test_formal_owner_error_envelope_maps_to_real_http(formal_app):
    app, _, _ = formal_app
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/v2/kunlian/workflows/flow/versions", params=PARAMS, headers=HEADERS, json={"name": "duplicate"}
        )
    assert response.status_code == 409
    assert response.json()["status_code"] == VersionNameExistsError.Code

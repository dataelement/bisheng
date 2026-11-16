"""Formal partner writes no longer expose caller-controlled retry keys."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.open_endpoints.api.endpoints import kunlian_workflow_api as routes
from test.open_api.test_kunlian_formal_http import HEADERS, PARAMS
from test.open_api.test_kunlian_formal_http import formal_app as formal_app


@pytest.mark.parametrize("operation", ["create", "start", "answer", "grant", "revoke"])
async def test_writes_accept_no_client_key_and_never_reuse_legacy_header(formal_app, monkeypatch, operation):
    app, management, _ = formal_app
    calls = []
    row = SimpleNamespace(session_id="a" * 32, workflow_id="f" * 32, workflow_version_id=3, status="QUEUED")

    async def submit(subject, key, body):
        calls.append(key)
        return row, True

    async def answer(subject, session_id, interaction_id, key, body):
        calls.append(key)
        return {"accepted": True}, True

    async def change(access, workflow_id, body, key):
        calls.append(key)
        return {"status": "APPLIED"}

    async def create(user, request, body, key):
        calls.append(key)
        return {"id": "f" * 32, "version_id": 3}

    management.create.side_effect = create
    monkeypatch.setattr(routes, "run_subject_from_request", lambda access: object())
    monkeypatch.setattr(
        routes, "get_kunlian_runtime_service", AsyncMock(return_value=SimpleNamespace(submit=submit, answer=answer))
    )
    monkeypatch.setattr(routes, "permission_api", AsyncMock(return_value=SimpleNamespace(change=change)))
    workflow = "/api/v2/kunlian/workflows/" + "f" * 32
    run = "/api/v2/kunlian/workflow-runs/" + "a" * 32
    path, body = {
        "create": ("/api/v2/kunlian/workflows", {"name": "new"}),
        "start": ("/api/v2/kunlian/workflow-runs", {"workflow_id": "f" * 32}),
        "answer": (run + "/interactions/" + "b" * 32 + "/submit", {"input": {"q": "answer"}}),
        "grant": (
            workflow + "/permissions/grants",
            {
                "expected_resource_version": 1,
                "expected_catalog_release_id": 1,
                "subject_ref": "target",
                "model_key": "model",
            },
        ),
        "revoke": (
            workflow + "/permissions/grants/1/revoke",
            {"expected_resource_version": 1, "expected_catalog_release_id": 1, "expected_assignee_version": 1},
        ),
    }[operation]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        headers = {key: value for key, value in HEADERS.items() if key != "Idempotency-Key"}
        response = await client.post(path, params=PARAMS, headers=headers, json=body)
        assert response.status_code in {200, 201, 202}, response.text
        for _ in range(2):
            response = await client.post(
                path, params=PARAMS, headers=headers | {"Idempotency-Key": "legacy-same"}, json=body
            )
            assert response.status_code in {200, 201, 202}, response.text
    assert len(calls) == len(set(calls)) == 3
    assert all(key != "legacy-same" for key in calls)


def test_formal_openapi_has_no_client_idempotency_parameter(formal_app):
    app, _, _ = formal_app
    for path, operations in app.openapi()["paths"].items():
        for method, contract in operations.items():
            if method in {"get", "post", "put", "patch"}:
                assert all(
                    parameter["name"].lower() != "idempotency-key" for parameter in contract.get("parameters", [])
                ), path
                query = {p["name"] for p in contract.get("parameters", []) if p["in"] == "query"}
                assert "user_account" in query, path
                assert not query & {"external_tenant_id", "external_user_id"}, path

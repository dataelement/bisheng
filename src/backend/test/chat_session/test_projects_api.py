"""AC-01, AC-08, AC-10, AC-11, AC-12: real routes, services and SQL."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from test.chat_session.test_projects_repository import repo as _repo_fixture

repo = _repo_fixture


@pytest.fixture
async def client(repo, monkeypatch):
    from bisheng.chat_session.api.endpoints.projects import router
    from bisheng.chat_session.domain.services import project_service
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode

    monkeypatch.setattr(project_service, "publish_project_change", AsyncMock(return_value="live"))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7, tenant_id=1)

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.return_resp_instance().model_dump())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield client


async def test_create_read_back_and_reject_owner_injection(client):
    response = await client.post(
        "/api/v1/chat/projects/actions", json={"request_id": str(uuid4()), "operation": "create", "name": "API"}
    )
    assert response.status_code == 200
    assert response.json()["status_code"] == 200
    snapshot = (await client.get("/api/v1/chat/projects/snapshot")).json()
    assert snapshot["status_code"] == 200
    assert snapshot["data"]["projects"][0]["name"] == "API"
    refused = await client.post(
        "/api/v1/chat/projects/actions",
        json={"request_id": str(uuid4()), "operation": "create", "name": "Wrong", "user_id": 8},
    )
    assert refused.json()["status_code"] == 13012
    assert len((await client.get("/api/v1/chat/projects/snapshot")).json()["data"]["projects"]) == 1


async def test_foreign_conversation_refused_and_no_orphan_project(client):
    response = await client.post(
        "/api/v1/chat/projects/actions",
        json={"request_id": str(uuid4()), "operation": "create", "name": "Bad", "chat_id": "foreign"},
    )
    assert response.json()["status_code"] == 13015
    assert (await client.get("/api/v1/chat/projects/snapshot")).json()["data"]["projects"] == []


async def test_batch_import_is_read_back_and_reports_foreign_member(client):
    response = await client.post(
        "/api/v1/chat/projects/actions",
        json={
            "request_id": str(uuid4()),
            "operation": "import",
            "source_client_id": str(uuid4()),
            "projects": [{"legacy_id": "old", "name": "Legacy"}],
            "memberships": [{"chat_id": "foreign", "legacy_project_id": "old"}],
        },
    )
    assert response.json()["status_code"] == 200
    assert response.json()["data"]["outcome"]["items"][1]["status"] == "conversation_unavailable"
    snapshot = (await client.get("/api/v1/chat/projects/snapshot")).json()["data"]
    assert len(snapshot["projects"]) == 1 and snapshot["memberships"] == []

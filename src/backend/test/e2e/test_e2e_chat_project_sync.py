"""Project API end-to-end through real ASGI routes, services and isolated SQL.

Authentication is injected at the existing dependency boundary using dedicated
synthetic actors. JWT/Gateway, Redis replicas and native UI are separate checks;
this suite never contacts a deployed environment or reads production credentials.
"""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from test.chat_session.test_projects_repository import repo as _repo_fixture
from test.e2e.helpers.api import assert_resp_200, assert_resp_error

repo = _repo_fixture
PREFIX = "e2e-project-"
API = "/api/v1/chat/projects"


async def mutate(client, operation):
    if operation["operation"] == "create":
        operation = {"project_id": str(uuid4()), **operation}
    return await client.post(f"{API}/actions", json=operation)


async def cleanup_projects(client):
    page = assert_resp_200(await client.get(f"{API}/snapshot"))
    owned = [project["id"] for project in page["projects"] if project["name"].startswith(PREFIX)]
    for project_id in owned:
        assert_resp_200(await mutate(client, {"operation": "delete", "project_id": project_id}))


@pytest.fixture
async def clients(repo, monkeypatch):
    from bisheng.chat_session.api.endpoints.projects import router
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actors = {"owner": (7, 1), "other": (8, 1), "tenant": (7, 2), "admin": (9, 1)}

    def identity(request: Request):
        user_id, tenant_id = actors[request.headers.get("X-Test-Actor", "owner")]
        return SimpleNamespace(
            user_id=user_id, tenant_id=tenant_id, is_global_super=request.headers.get("X-Test-Actor") == "admin"
        )

    app.dependency_overrides[UserPayload.get_login_user] = identity

    @app.exception_handler(BaseErrorCode)
    async def error(request, exception):
        return JSONResponse(exception.return_resp_instance().model_dump())

    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as web,
        httpx.AsyncClient(transport=transport, base_url="http://test") as desktop,
    ):
        await cleanup_projects(web)
        try:
            yield web, desktop
        finally:
            await cleanup_projects(web)


async def test_ac01_ac02_ac04_ac05_two_clients_share_actions_and_membership(clients):
    """AC-01, AC-02, AC-04, AC-05: read each client's writes through the other."""
    web, desktop = clients
    created = assert_resp_200(await mutate(web, {"operation": "create", "name": PREFIX + "shared"}))
    project = created["outcome"]["project_id"]
    assert_resp_200(await mutate(desktop, {"operation": "assign", "project_id": project, "chat_id": "chat-124"}))
    web_state = assert_resp_200(await web.get(f"{API}/snapshot"))
    desktop_state = assert_resp_200(await desktop.get(f"{API}/snapshot"))
    assert web_state == desktop_state
    page = assert_resp_200(await web.get(f"{API}/conversations", params={"project_id": project}))
    assert page["data"][0]["chat_id"] == "chat-124"
    assert_resp_200(await mutate(desktop, {"operation": "delete", "project_id": project}))
    final = assert_resp_200(await web.get(f"{API}/snapshot"))
    assert final["projects"] == [] and final["memberships"] == []


async def test_ac06_ac07_ac08_retried_create_does_not_restore_stale_name(clients):
    """AC-06, AC-07, AC-08: retry the exact uncertain create after a later edit."""
    web, desktop = clients
    operation = {"operation": "create", "project_id": str(uuid4()), "name": PREFIX + "initial"}
    first = assert_resp_200(await mutate(web, operation))
    project = first["outcome"]["project_id"]
    assert_resp_200(await mutate(desktop, {"operation": "rename", "project_id": project, "name": PREFIX + "current"}))
    retry = assert_resp_200(await mutate(web, operation))
    assert retry["outcome"]["project_id"] == project
    state = assert_resp_200(await web.get(f"{API}/snapshot"))
    assert [row["name"] for row in state["projects"]] == [PREFIX + "current"]


@pytest.mark.parametrize("actor", ["other", "tenant", "admin"])
async def test_ac09_ac10_foreign_identity_cannot_read_or_mutate_private_projects(clients, actor):
    """AC-09, AC-10: root/admin identity and known ids do not grant private access."""
    web, desktop = clients
    project = assert_resp_200(await mutate(web, {"operation": "create", "name": PREFIX + "private"}))["outcome"][
        "project_id"
    ]
    desktop.headers["X-Test-Actor"] = actor
    assert assert_resp_200(await desktop.get(f"{API}/snapshot"))["projects"] == []
    assert_resp_error(await mutate(desktop, {"operation": "rename", "project_id": project, "name": "stolen"}), 13011)
    assert_resp_error(await desktop.get(f"{API}/conversations", params={"project_id": project}), 13011)
    assert assert_resp_200(await web.get(f"{API}/snapshot"))["projects"][0]["name"] == PREFIX + "private"


async def test_ac11_ac12_import_merges_once_and_preserves_later_cloud_changes(clients):
    """AC-11, AC-12: import is a merge by conversation owner, not a snapshot overwrite."""
    web, desktop = clients
    payload = {
        "operation": "import",
        "projects": [{"legacy_id": "browser-old", "name": PREFIX + "legacy"}],
        "memberships": [
            {"chat_id": "chat-001", "legacy_project_id": "browser-old"},
            {"chat_id": "foreign", "legacy_project_id": "browser-old"},
        ],
    }
    result = assert_resp_200(await mutate(web, payload))
    assert result["outcome"]["items"][-1]["status"] == "conversation_unavailable"
    project = assert_resp_200(await desktop.get(f"{API}/snapshot"))["projects"][0]["id"]
    assert_resp_200(await mutate(desktop, {"operation": "assign", "chat_id": "chat-001", "project_id": None}))
    assert_resp_200(await mutate(web, payload))
    assert assert_resp_200(await desktop.get(f"{API}/snapshot"))["memberships"] == []
    assert_resp_200(await mutate(desktop, {"operation": "delete", "project_id": project}))
    assert_resp_200(await mutate(web, payload))
    assert assert_resp_200(await desktop.get(f"{API}/snapshot"))["projects"] == []


async def test_ac11_ac12_other_account_takes_only_its_own_legacy_project(clients):
    """AC-11, AC-12: two accounts in one browser split the legacy record by conversation owner."""
    web, desktop = clients
    desktop.headers["X-Test-Actor"] = "other"
    payload = {
        "operation": "import",
        "projects": [{"legacy_id": "a", "name": PREFIX + "owner"}, {"legacy_id": "b", "name": PREFIX + "other"}],
        "memberships": [
            {"chat_id": "chat-002", "legacy_project_id": "a"},
            {"chat_id": "foreign", "legacy_project_id": "b"},
        ],
    }
    assert_resp_200(await mutate(web, payload))
    assert_resp_200(await mutate(desktop, payload))
    assert [p["name"] for p in assert_resp_200(await web.get(f"{API}/snapshot"))["projects"]] == [PREFIX + "owner"]
    other = assert_resp_200(await desktop.get(f"{API}/snapshot"))
    assert [p["name"] for p in other["projects"]] == [PREFIX + "other"]
    for project in other["projects"]:
        assert_resp_200(await mutate(desktop, {"operation": "delete", "project_id": project["id"]}))

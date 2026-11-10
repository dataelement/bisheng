"""覆盖 AC: AC-01, AC-02, AC-03, AC-06, AC-10, AC-11, AC-12, AC-21, AC-25。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.api.router import router
from bisheng.workflow.application import platform_agent as application
from bisheng.workflow.domain.services import platform_agent_service as domain


@pytest.fixture
def api(monkeypatch):
    repo = SimpleNamespace(get_workflow=lambda _: {"id": "flow", "tenant_id": 7, "flow_type": 10})
    service = domain.PlatformAgentService(
        repository=repo, config=PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B", "7:13": "C"})
    )
    monkeypatch.setattr(application, "get_service", lambda: service)
    authorization = AsyncMock()
    monkeypatch.setattr(
        domain,
        "read_current_person_facts",
        AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 0}}),
    )
    monkeypatch.setattr(domain, "require_business_action", authorization)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=12, tenant_id=7)
    return app, authorization


@pytest.mark.asyncio
async def test_directory_version_and_validation_use_the_local_actor(api):
    app, auth = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        first = await client.get("/api/v1/workflow/platform-agents", params={"workflow_id": "flow"})
        assert first.status_code == 200
        data = first.json()["data"]
        assert data["provider_mode"] == "mock" and data["data"]
        version = await client.get(
            "/api/v1/workflow/platform-agents/mock:echo/versions/v1", params={"workflow_id": "flow"}
        )
        assert version.status_code == 200 and version.json()["data"]["ref"]["version_id"] == "v1"
        invalid = await client.post(
            "/api/v1/workflow/platform-agents/validate",
            json={"workflow_id": "flow", "graph": {"nodes": []}, "user_id": 11, "token": "secret-probe"},
        )
        assert invalid.status_code == 422 and "secret-probe" not in invalid.text
        valid = await client.post(
            "/api/v1/workflow/platform-agents/validate",
            json={"workflow_id": "flow", "graph": {"nodes": [], "edges": []}},
        )
        assert valid.json()["data"]["valid"] is True
    assert auth.await_count == 3
    assert auth.await_args.kwargs["action"] == "edit"
    assert auth.await_args.args[0].user_id == 12


@pytest.mark.asyncio
async def test_local_denial_and_cross_tenant_fail_before_the_provider(api):
    app, auth = api
    auth.side_effect = UnAuthorizedError()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get("/api/v1/workflow/platform-agents", params={"workflow_id": "flow"})
        assert response.status_code == 403
        app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=12, tenant_id=8)
        response = await client.get("/api/v1/workflow/platform-agents", params={"workflow_id": "flow"})
        assert response.status_code == 403
    assert auth.await_count == 1


@pytest.mark.asyncio
async def test_invalid_identity_and_unexpected_failure_never_echo_secret_input(api, monkeypatch):
    app, auth = api
    monkeypatch.setattr(
        domain,
        "read_current_person_facts",
        AsyncMock(return_value={12: {"state": "inactive", "tenant_id": 7, "token_version": 0}}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        denied = await client.get("/api/v1/workflow/platform-agents", params={"workflow_id": "flow"})
        assert denied.status_code == 403
        auth.assert_not_awaited()
        bad = await client.post("/api/v1/workflow/platform-agents/validate", json=["secret-probe"])
        assert bad.status_code == 422 and "secret-probe" not in bad.text
        monkeypatch.setattr(domain, "read_current_person_facts", AsyncMock(side_effect=RuntimeError("secret-probe")))
        failed = await client.get("/api/v1/workflow/platform-agents", params={"workflow_id": "flow"})
        assert failed.status_code == 503 and "secret-probe" not in failed.text


@pytest.mark.asyncio
async def test_changing_version_checks_inputs_and_downstream_output_references(api):
    app, _ = api
    reference = {"agent_id": "mock:echo", "version_id": "v1"}
    bindings = {"query": {"source": "constant", "value": "hello"}}
    graph = {
        "nodes": [
            {
                "data": {
                    "id": "platform_agent_1",
                    "type": "platform_agent",
                    "group_params": [
                        {
                            "params": [
                                {"key": "agent_ref", "value": reference},
                                {"key": "input_bindings", "value": bindings},
                            ]
                        }
                    ],
                }
            },
            {
                "data": {
                    "id": "output_1",
                    "type": "output",
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "message",
                                    "type": "var_textarea_file",
                                    "value": {"msg": "{{#platform_agent_1.result#answer#}}", "files": []},
                                }
                            ]
                        }
                    ],
                }
            },
        ],
        "edges": [],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:

        async def validate():
            return (
                await client.post(
                    "/api/v1/workflow/platform-agents/validate", json={"workflow_id": "flow", "graph": graph}
                )
            ).json()["data"]

        assert (await validate())["valid"]
        reference["version_id"] = "v2"
        assert not (await validate())["valid"]
        bindings["question"] = bindings.pop("query")
        assert any(issue["node_id"] == "output_1" for issue in (await validate())["issues"])
        graph["nodes"][1]["data"]["group_params"][0]["params"][0]["value"]["msg"] = (
            "{{#platform_agent_1.result#reply#}}"
        )
        assert (await validate())["valid"]

"""覆盖 AC: AC-01, AC-02, AC-06, AC-12, AC-17。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.config.settings import PlatformKnowledgeConf
from bisheng.workflow.api.router import router
from bisheng.workflow.application import platform_knowledge
from bisheng.workflow.domain.services import platform_knowledge_service as domain


async def test_directory_and_validation_share_actual_editor(monkeypatch):
    actor = SimpleNamespace(user_id=12, tenant_id=7)
    repo = SimpleNamespace(get_workflow=lambda _: {"tenant_id": 7, "flow_type": 10})
    service = domain.PlatformKnowledgeService(
        config=PlatformKnowledgeConf(),
        repository=repo,
        identity_reader=AsyncMock(return_value={12: {"state": "active", "tenant_id": 7, "token_version": 0}}),
    )
    monkeypatch.setattr(platform_knowledge, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        url = "/api/v1/workflow/platform-knowledge"
        result = await client.get(url, params={"workflow_id": "flow"})
        assert result.status_code == 200 and result.json()["data"]["items"]
        detail = await client.get(url + "/mock:maintenance", params={"workflow_id": "flow"})
        assert detail.json()["data"]["resource_id"] == "mock:maintenance"
        invalid = await client.post(url + "/validate", json={"workflow_id": "flow", "graph": {}, "tenant_id": 7})
        assert invalid.status_code == 400
        actor.tenant_id = 8
        assert (await client.get(url, params={"workflow_id": "flow"})).status_code == 403

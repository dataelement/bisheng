"""HTTP contract for E+ robot configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.api.services import assistant as assistant_service_module
from bisheng.api.services.assistant import AssistantService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.assistant import Assistant, AssistantStatus
from bisheng.eplus.api.endpoints.bot_config import get_eplus_bot_config_service
from bisheng.eplus.api.router import router
from bisheng.eplus.domain.schemas.config import EPlusBotConfigView


class FakeConfigService:
    def __init__(self) -> None:
        self.view: EPlusBotConfigView | None = None
        self.get_calls: list[dict] = []

    async def get_config(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.view

    async def save_config(self, *, assistant_id, request, **kwargs):
        self.view = EPlusBotConfigView(
            id=1,
            assistant_id=assistant_id,
            bot_id=request.bot_id,
            connection_url=request.connection_url,
            credential_version=1,
            scope_version=1,
            enabled=request.enabled,
            is_deleted=False,
            connection_status="DISABLED",
            secret_configured=request.secret is not None,
            ca_configured=False,
            ca_sha256=None,
            media_hosts=tuple(request.media_hosts),
            space_ids=tuple(request.space_ids),
            insecure_transport=request.connection_url.startswith("ws://"),
        )
        return self.view

    async def disable_config(self, **kwargs):
        self.view = None
        return True


def _client(service: FakeConfigService) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_eplus_bot_config_service] = lambda: service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=9,
        user_name="admin",
        user_role=[1],
        tenant_id=73,
    )
    return TestClient(app)


def test_get_create_and_delete_robot_configuration_without_secret_echo() -> None:
    service = FakeConfigService()
    client = _client(service)

    assert client.get("/api/v1/eplus/assistants/assistant-1/bot").json()["data"] is None
    assert service.get_calls == [{"tenant_id": 73, "assistant_id": "assistant-1", "operator_id": 9}]
    response = client.put(
        "/api/v1/eplus/assistants/assistant-1/bot",
        json={
            "bot_id": "bot-1",
            "connection_url": "ws://eplus.example.test/im_openws?bizid=1",
            "secret": "never-echo-this",
            "media_hosts": ["media.example.test"],
            "space_ids": [20, 10],
            "enabled": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["secret_configured"] is True
    assert data["insecure_transport"] is True
    assert data["space_ids"] == [10, 20]
    assert "never-echo-this" not in response.text

    response = client.delete("/api/v1/eplus/assistants/assistant-1/bot")
    assert response.status_code == 200
    assert response.json()["data"] is True


def test_put_rejects_non_websocket_connection_url() -> None:
    client = _client(FakeConfigService())
    response = client.put(
        "/api/v1/eplus/assistants/assistant-1/bot",
        json={
            "bot_id": "bot-1",
            "connection_url": "https://eplus.example.test/im_openws",
            "secret": "secret",
        },
    )
    assert response.status_code == 422


async def test_assistant_online_and_offline_publish_target_change_after_update(monkeypatch) -> None:
    assistant = Assistant(
        id="assistant-1",
        name="E+ assistant",
        tenant_id=73,
        user_id=9,
        status=AssistantStatus.OFFLINE.value,
    )
    update = AsyncMock()
    notify = AsyncMock()

    monkeypatch.setattr(
        assistant_service_module.AssistantDao,
        "get_one_assistant",
        lambda assistant_id: assistant,
    )
    monkeypatch.setattr(
        assistant_service_module.AssistantDao,
        "update_assistant",
        lambda value: value,
    )
    monkeypatch.setattr(assistant_service_module, "require_business_action", AsyncMock())
    monkeypatch.setattr(assistant_service_module.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(AssistantService, "update_assistant_hook", lambda *args: True)
    monkeypatch.setattr(assistant_service_module, "notify_eplus_assistant_target_changed", notify)

    class FakeAssistantAgent:
        def __init__(self, *args) -> None:
            pass

        async def init_assistant(self) -> None:
            await update()

    monkeypatch.setattr(assistant_service_module, "AssistantAgent", FakeAssistantAgent)
    login_user = UserPayload(user_id=9, user_name="admin", user_role=[1], tenant_id=73)

    assert await AssistantService.update_status(
        object(), login_user, "assistant-1", AssistantStatus.ONLINE.value
    )
    assert await AssistantService.update_status(
        object(), login_user, "assistant-1", AssistantStatus.OFFLINE.value
    )

    update.assert_awaited_once()
    assert notify.await_args_list[0].kwargs == {"tenant_id": 73, "assistant_id": "assistant-1"}
    assert notify.await_args_list[1].kwargs == {"tenant_id": 73, "assistant_id": "assistant-1"}

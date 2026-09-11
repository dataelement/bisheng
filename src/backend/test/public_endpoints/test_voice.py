"""Exercise public speech HTTP requests through the real publication policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.assistant import AssistantStatus
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.public_endpoints.api.endpoints import llm
from bisheng.public_endpoints.api.exception_handlers import register_public_exception_handlers
from bisheng.public_endpoints.api.router import router_public
from bisheng.public_endpoints.domain.context import get_current_public_api_principal
from bisheng.public_endpoints.domain.services import guest_policy

WORKFLOW_ID = UUID(int=101).hex
ASSISTANT_ID = UUID(int=102).hex
OPERATIONS = ("config", "asr", "tts")


@pytest.fixture
def publication(monkeypatch):
    workflow = SimpleNamespace(tenant_id=3, flow_type=FlowType.WORKFLOW.value, status=FlowStatus.ONLINE.value)
    assistant = SimpleNamespace(tenant_id=9, is_delete=False, status=AssistantStatus.ONLINE.value)
    state = SimpleNamespace(enabled=True, workflow=workflow, assistant=assistant, calls=[])
    monkeypatch.setattr(
        guest_policy.FlowDao,
        "aget_flow_by_id",
        AsyncMock(side_effect=lambda resource_id: workflow if resource_id == WORKFLOW_ID else None),
    )
    monkeypatch.setattr(
        guest_policy.AssistantDao,
        "aget_one_assistant",
        AsyncMock(side_effect=lambda resource_id: assistant if resource_id == ASSISTANT_ID else None),
    )
    monkeypatch.setattr(
        guest_policy,
        "settings",
        SimpleNamespace(
            aget_from_db=AsyncMock(
                side_effect=lambda _key: {"enable_guest_access": state.enabled, "user": 100 + get_current_tenant_id()},
            )
        ),
    )
    monkeypatch.setattr(
        guest_policy.UserDao,
        "aget_user",
        AsyncMock(
            side_effect=lambda user_id: SimpleNamespace(user_id=user_id, user_name="publisher", delete=False),
        ),
    )
    monkeypatch.setattr(
        guest_policy.UserTenantDao,
        "aget_user_tenant",
        AsyncMock(
            return_value=SimpleNamespace(status="active"),
        ),
    )
    monkeypatch.setattr(
        guest_policy.TenantDao,
        "aget_by_id",
        AsyncMock(
            return_value=SimpleNamespace(status="active"),
        ),
    )

    def record(operation, operator=None):
        tenant_id = get_current_tenant_id()
        principal = get_current_public_api_principal()
        assert principal.tenant_id == tenant_id
        assert get_current_permission_actor().subject_id == 100 + tenant_id
        if operator is not None:
            assert operator.user_id == 100 + tenant_id
            assert operator.tenant_id == tenant_id
        state.calls.append((operation, tenant_id, principal.resource_id))
        return tenant_id

    async def config():
        tenant_id = record("config")
        return SimpleNamespace(
            asr_model=SimpleNamespace(id=f"asr-{tenant_id}", name="internal model"),
            tts_model=SimpleNamespace(id=f"tts-{tenant_id}", name="internal model"),
            task_model=SimpleNamespace(id="private-config"),
        )

    async def asr(operator, file):
        assert await file.read() == b"test-audio"
        return f"transcript-{record('asr', operator)}"

    async def tts(operator, text):
        assert text == "Read this"
        return f"https://media.example/speech-{record('tts', operator)}.mp3"

    monkeypatch.setattr(llm.LLMService, "get_workbench_llm", config)
    monkeypatch.setattr(llm.LLMService, "invoke_workbench_asr", asr)
    monkeypatch.setattr(llm.LLMService, "invoke_workbench_tts", tts)
    return state


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(router_public)
    register_public_exception_handlers(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as value:
        yield value


async def request_voice(client, operation, flow_id, **kwargs):
    params = {} if flow_id is None else {"flow_id": flow_id}
    if operation == "config":
        return await client.get("/api/v3/llm/workbench", params=params, **kwargs)
    if operation == "asr":
        return await client.post(
            "/api/v3/llm/workbench/asr",
            params=params,
            files={"file": ("recording.wav", b"test-audio", "audio/wav")},
            **kwargs,
        )
    return await client.post(
        "/api/v3/llm/workbench/tts",
        params=params,
        json={"text": "Read this"},
        **kwargs,
    )


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_published_voice_without_credentials_keeps_resource_tenant(client, publication, operation):
    """AC-R9: Both application types work anonymously without leaking tenant context."""
    for flow_id, tenant_id in ((WORKFLOW_ID, 3), (ASSISTANT_ID, 9)):
        response = await request_voice(client, operation, str(UUID(flow_id)))
        assert response.status_code == 200
        body = response.json()
        assert body["status_code"] == 200
        assert body["status_message"] == "SUCCESS"
        if operation == "config":
            assert body["data"] == {"asr_model": {"id": f"asr-{tenant_id}"}, "tts_model": {"id": f"tts-{tenant_id}"}}
        elif operation == "asr":
            assert body["data"] == f"transcript-{tenant_id}"
        else:
            assert body["data"] == f"https://media.example/speech-{tenant_id}.mp3"
        assert publication.calls[-1] == (operation, tenant_id, flow_id)
        assert get_current_tenant_id() is None
        assert get_current_public_api_principal() is None
        assert get_current_permission_actor() is None


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("failure,status", [("disabled", 403), ("offline", 404)])
async def test_publication_denial_prevents_voice_model_access(client, publication, operation, failure, status):
    """AC-R9: Closed guest access and unpublished apps never reach a model."""
    if failure == "disabled":
        publication.enabled = False
    else:
        publication.workflow.status = -1
    response = await request_voice(client, operation, WORKFLOW_ID)
    assert response.status_code == status
    assert response.json()["status_code"] == status
    assert publication.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("flow_id", [None, "invalid-id"])
async def test_application_id_is_required(client, publication, operation, flow_id):
    """AC-R9: Speech never falls back to an unscoped default tenant."""
    response = await request_voice(client, operation, flow_id)
    assert response.status_code == 422
    assert publication.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("header", ["X-On-Behalf-Of", "X-End-User"])
async def test_public_voice_rejects_identity_headers(client, publication, operation, header):
    response = await request_voice(client, operation, WORKFLOW_ID, headers={header: "123"})
    assert response.status_code == 403
    assert response.json()["status_code"] == 403
    assert publication.calls == []


async def test_missing_voice_models_return_disabled_controls(client, publication, monkeypatch):
    monkeypatch.setattr(
        llm.LLMService,
        "get_workbench_llm",
        AsyncMock(
            return_value=SimpleNamespace(asr_model=None, tts_model=None),
        ),
    )
    response = await request_voice(client, "config", WORKFLOW_ID)
    assert response.json()["data"] == {"asr_model": {"id": None}, "tts_model": {"id": None}}

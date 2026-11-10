"""覆盖 AC: AC-22, AC-23, AC-26, AC-34."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from bisheng.dsh.api.endpoints import identity
from bisheng.dsh.config import DshSettings
from test.dsh import test_model_service, test_models_api

service_setup = test_model_service.service_setup
app_setup = test_models_api.app_setup


async def test_config_declares_optional_fields_without_tenant_mode(monkeypatch):
    monkeypatch.setattr(identity.DshSettingsService, "read", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    settings = DshSettings(
        enabled=True, platform_public_url="https://example.test", gateway_internal_url="https://gateway.test"
    )
    result = await identity.config(settings)
    assert result["audit_context"] == {
        "fields": ["conversation_id", "request_kind", "session_origin", "parent_conversation_id", "message_sources"]
    }
    assert "mode" not in result and result["contract_version"] == "0.5.0"
    assert result["audit_conversation_title"] == {"version": 1}
    assert await identity.config(DshSettings()) == {"enabled": False}


@pytest.mark.parametrize(
    "audit_context",
    [
        {"conversation_id": "real-session", "request_kind": "chat"},
        {"conversation_id": 1, "request_kind": "compaction"},
        [],
        "bad",
        {"conversation_id": "x" * 257},
        {"request_kind": "unknown"},
    ],
)
async def test_optional_extension_never_rejects_or_replays_legal_request(app_setup, audit_context):
    app, _runtime, model_runtime, llm, _ledger = app_setup
    original = model_runtime.complete
    observed = []

    async def complete(principal, body, **kwargs):
        observed.append(kwargs)
        assert not hasattr(body, "audit_context")
        return await original(principal, body, **kwargs)

    model_runtime.complete = complete
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test"},
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "synthetic"}],
                "audit_context": audit_context,
            },
        )
    assert response.status_code == 200
    assert llm.calls == 1
    assert observed[0]["request_id"] == response.json()["id"].removeprefix("chatcmpl-")
    assert observed[0]["audit_context"] is not None


@pytest.mark.parametrize("body", ["}{", "[]", "null", '{"model":"bisheng:42","messages":"invalid"}'])
async def test_malformed_json_or_business_data_remains_invalid(app_setup, body):
    app, _runtime, _model, llm, ledger = app_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={
                "Authorization": "Bearer test",
                "Content-Type": "application/json",
            },
            content=body,
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert llm.calls == 0 and ledger.events == []

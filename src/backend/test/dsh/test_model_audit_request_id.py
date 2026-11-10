"""覆盖 AC: AC-15, AC-23, AC-36."""

from unittest.mock import AsyncMock

import httpx

from bisheng.common.errcode.dsh import DshUpstreamErrorError
from test.dsh import test_model_service, test_models_api

service_setup = test_model_service.service_setup
app_setup = test_models_api.app_setup


async def test_upstream_failure_response_id_matches_business_call(app_setup):
    app, _runtime, _model, llm, ledger = app_setup
    llm.ainvoke = AsyncMock(side_effect=DshUpstreamErrorError())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test"},
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "synthetic"}],
            },
        )
    assert response.status_code == 502
    assert response.json()["request_id"] == ledger.events[0].request_id
    assert all(event.request_id == response.json()["request_id"] for event in ledger.events)


async def test_invalid_business_parameters_never_start_usage(app_setup):
    app, _runtime, _model, llm, ledger = app_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test"},
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "synthetic"}],
                "forged": 1,
                "audit_context": {"conversation_id": "valid"},
            },
        )
    assert response.status_code == 400 and response.json()["request_id"]
    assert llm.calls == 0 and ledger.events == []


async def test_settlement_failure_does_not_replace_request_id_or_replay(app_setup):
    app, _runtime, _model, llm, ledger = app_setup
    ledger.record_usage = AsyncMock(side_effect=OSError("synthetic settlement failure"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test"},
            json={
                "model": "bisheng:42",
                "messages": [{"role": "user", "content": "synthetic"}],
            },
        )
    assert response.status_code == 503
    assert response.json()["request_id"] == ledger.events[0].request_id
    assert llm.calls == 1

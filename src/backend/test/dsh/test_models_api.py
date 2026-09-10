"""Frozen HTTP and stream lifetime regressions. AC-18, AC-20, AC-23, AC-31, AC-34."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError, DshQuotaUnavailableError
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints import models as endpoints
from bisheng.dsh.domain.services.model import PreparedStream
from test.dsh.test_model_service import principal, service_setup  # noqa: F401


@pytest.fixture
def app_setup(monkeypatch, service_setup):  # noqa: F811
    service, llm, ledger, _policy, _state = service_setup
    runtime = SimpleNamespace(
        settings=SimpleNamespace(billing_timezone="Asia/Shanghai"),
        access=SimpleNamespace(authenticate=AsyncMock(return_value=principal())),
    )
    model_runtime = SimpleNamespace(
        model=service,
        complete=service.complete,
        prepare_month=AsyncMock(side_effect=DshQuotaUnavailableError()),
    )
    monkeypatch.setattr(endpoints, "get_model_runtime", AsyncMock(return_value=model_runtime))
    monkeypatch.setattr(endpoints, "read_persisted_usage", AsyncMock(side_effect=ValueError()))
    monkeypatch.setattr(endpoints, "read_policy", AsyncMock(return_value=SimpleNamespace(monthly_token_limit=100)))
    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app, runtime, model_runtime, llm, ledger


async def test_cookie_never_substitutes_for_desktop_bearer(app_setup):
    app, runtime, *_ = app_setup
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.get("/api/v1/dsh/models", headers={"Cookie": "access_token=browser"})
        assert response.status_code == 401 and runtime.access.authenticate.await_count == 0
        runtime.access.authenticate.side_effect = DshInvalidAccessTokenError()
        assert (await client.get("/api/v1/dsh/usage", headers={"Authorization": "Bearer PAT"})).status_code == 401


@pytest.mark.parametrize("reliable", [True, False])
async def test_real_model_service_json_and_sse_contract(app_setup, reliable):
    app, _runtime, _model, llm, ledger = app_setup
    llm.reliable = reliable
    llm.continue_stream.set()
    headers = {"Authorization": "Bearer dedicated"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        listed = await client.get("/api/v1/dsh/models", headers=headers)
        assert listed.json()["data"][0]["id"] == "bisheng:42"
        body = {
            "model": "bisheng:42",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        response = await client.post("/api/v1/dsh/chat/completions", json=body, headers=headers)
        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-store"
        assert "first" in response.text
        assert "[DONE]" in response.text
        assert "usage_unavailable" not in response.text
        assert ledger.events[-1].total_tokens == (12 if reliable else None)
        assert not ledger.frozen
        if not reliable:
            assert '"total_tokens":null' in response.text
        # Unknown parameters are rejected before upstream admission.
        body["user_id"] = "999"
        assert (await client.post("/api/v1/dsh/chat/completions", json=body, headers=headers)).status_code == 400
        assert llm.calls == 1


@pytest.mark.parametrize("stream,include_usage", [(False, False), (True, True), (True, False)])
async def test_cache_details_on_http_responses_and_settlement(app_setup, stream, include_usage):
    """AC-22/23: Cache details reach JSON/SSE; omitted SSE usage still settles them."""
    app, _, _, llm, ledger = app_setup
    llm.measured = lambda: {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "input_token_details": {"cache_read": 8, "cache_creation": 1},
    }
    llm.continue_stream.set()
    body = {"model": "bisheng:42", "messages": [{"role": "user", "content": "test"}], "stream": stream}
    if include_usage:
        body["stream_options"] = {"include_usage": True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions", json=body, headers={"Authorization": "Bearer dedicated"}
        )
    assert response.status_code == 200
    if stream:
        assert response.text.endswith("data: [DONE]\n\n")
        chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
        usages = [chunk["usage"] for chunk in chunks if "usage" in chunk]
        assert bool(usages) is include_usage
    else:
        usages = [response.json()["usage"]]
    for usage in usages:
        assert usage["prompt_tokens_details"] == {"cached_tokens": 8, "cache_creation_tokens": 1}
        assert usage["total_tokens"] == 12
    assert ledger.events[-1].cache_read_tokens == 8
    assert ledger.events[-1].cache_creation_tokens == 1
    assert ledger.used == 102


async def test_usage_fallback_keeps_unknown_null_and_projection_time(app_setup, monkeypatch):
    app, _runtime, model_runtime, *_ = app_setup
    headers = {"Authorization": "Bearer dedicated"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        result = (await client.get("/api/v1/dsh/usage", headers=headers)).json()
        assert result["used"] is None and result["remaining"] is None and result["as_of"] is None
        assert result["limit"] == 100 and result["source"] == result["quota_state"] == "unavailable"
        snapshot = {
            "used": 120,
            "limit": 100,
            "remaining": 0,
            "source": "sql_estimate",
            "as_of": datetime(2026, 9, 1),
            "quota_state": "unavailable",
        }
        monkeypatch.setattr(endpoints, "read_persisted_usage", AsyncMock(return_value=snapshot))
        result = (await client.get("/api/v1/dsh/usage", headers=headers)).json()
        assert result["source"] == "persisted" and result["quota_state"] == "unavailable"
        assert result["as_of"] == "2026-09-01T00:00:00Z"
        model_runtime.prepare_month = AsyncMock(return_value={**snapshot, "source": "live", "quota_state": "ready"})
        assert (await client.get("/api/v1/dsh/usage", headers=headers)).json()["quota_state"] == "exhausted"
        model_runtime.prepare_month = AsyncMock(
            return_value={**snapshot, "used": 2, "remaining": 98, "source": "live", "quota_state": "blocked"}
        )
        assert (await client.get("/api/v1/dsh/usage", headers=headers)).json()["quota_state"] == "unavailable"


def test_billing_month_uses_timezone_and_year_rollover():
    result = endpoints.billing_period(datetime(2026, 12, 31, 16, tzinfo=UTC), "Asia/Shanghai")
    assert result["month"] == "2027-01"
    assert result["period_start"] == "2026-12-31T16:00:00Z"
    assert result["reset_at"] == "2027-01-31T16:00:00Z"


async def test_response_closes_prepared_stream_if_send_fails_before_first_read(service_setup):  # noqa: F811
    from test.dsh.test_model_service import request

    service, llm, ledger, *_ = service_setup
    stream = await service.complete(principal(), request(stream=True))
    assert isinstance(stream, PreparedStream)
    response = endpoints.DshStreamingResponse(stream)

    async def send(_message):
        raise OSError("Peer disconnected before headers")

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, AsyncMock(), send)
    assert llm.calls == 0 and stream.closed
    assert ledger.events[-1].status == "CANCELLED" and ledger.events[-1].total_tokens == 0


async def test_usage_selected_model_cannot_borrow_another_allowance(app_setup, monkeypatch):
    from bisheng.dsh.domain.schemas.model_policy import DshModelQuotaConfig

    app, _runtime, model_runtime, *_ = app_setup
    policy = SimpleNamespace(
        model_configs=[
            DshModelQuotaConfig(model_id=42, monthly_token_limit=100),
            DshModelQuotaConfig(model_id=43, monthly_token_limit=200),
        ]
    )
    monkeypatch.setattr(endpoints, "read_policy", AsyncMock(return_value=policy))
    model_runtime.prepare_month = AsyncMock(
        return_value={
            "used": 180,
            "limit": 300,
            "remaining": 150,
            "models": {"42": 130, "43": 50},
            "model_limits": {"42": 100, "43": 200},
            "source": "live",
            "quota_state": "ready",
            "as_of": datetime(2026, 9, 1),
        }
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        headers = {"Authorization": "Bearer dedicated"}
        exhausted = (await client.get("/api/v1/dsh/usage?model=bisheng:42", headers=headers)).json()
        available = (await client.get("/api/v1/dsh/usage?model=bisheng:43", headers=headers)).json()
        total = (await client.get("/api/v1/dsh/usage", headers=headers)).json()
        assert (exhausted["used"], exhausted["limit"], exhausted["remaining"], exhausted["quota_state"]) == (
            130,
            100,
            0,
            "exhausted",
        )
        assert (available["used"], available["limit"], available["remaining"], available["quota_state"]) == (
            50,
            200,
            150,
            "available",
        )
        assert total["remaining"] == 150
        denied = await client.get("/api/v1/dsh/usage?model=bisheng:99", headers=headers)
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "model_not_allowed"

        model_runtime.prepare_month.return_value["models"].pop("43")
        missing = (await client.get("/api/v1/dsh/usage?model=bisheng:43", headers=headers)).json()
        assert missing["used"] is None and missing["remaining"] is None
        assert missing["limit"] == 200 and missing["quota_state"] == "unavailable"

        monkeypatch.setattr(endpoints, "read_policy", AsyncMock(side_effect=RuntimeError("Database unavailable")))
        failed = await client.get("/api/v1/dsh/usage?model=bisheng:43", headers=headers)
        assert failed.status_code == 503 and failed.json()["error"]["code"] == "quota_unavailable"


async def test_missing_usage_json_returns_answer_and_next_call_remains_available(app_setup):
    """AC-23/24: missing usage stays nullable in audit without failing a completed answer."""
    app, _, _, llm, ledger = app_setup
    llm.reliable = False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        for _ in range(2):
            response = await client.post(
                "/api/v1/dsh/chat/completions",
                headers={"Authorization": "Bearer dedicated"},
                json={"model": "bisheng:42", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert response.status_code == 200
            assert response.json()["choices"][0]["message"]["content"] == "ok"
            assert response.json()["usage"] == {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "prompt_tokens_details": {"cached_tokens": None, "cache_creation_tokens": None},
            }
            assert ledger.events[-1].status == "USAGE_UNKNOWN"
            assert ledger.events[-1].error_code == "usage_missing"
        assert llm.calls == 2

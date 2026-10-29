"""Coverage AC: AC-62, AC-63. HTTP IDs are correlation, not authentication or execution proof."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlmodel import select

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError, DshUpstreamErrorError
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh import test_content_safety_merge, test_model_service, test_models_api
from test.dsh.test_content_safety_merge import (
    assert_external_unknowns,
    committed_merge,
    output_event,
    projection_port,
)
from test.dsh.test_content_safety_repository import tenant_session

app_setup = test_models_api.app_setup
service_setup = test_model_service.service_setup
metering_tables = test_content_safety_merge.metering_tables


@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
@pytest.mark.parametrize("stream", [False, True])
async def test_generic_http_id_reaches_model_runtime_without_gateway_dependency(app_setup, protocol, stream):
    app, _, runtime, _, _ = app_setup
    request_id = str(uuid4())
    runtime.complete = AsyncMock(return_value={"synthetic": True})
    payload = {"model": "bisheng:42", "stream": stream}
    payload.update(
        {"input": [{"role": "user", "content": "synthetic"}]}
        if protocol == "responses"
        else {"messages": [{"role": "user", "content": "synthetic"}]}
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/" + protocol,
            json=payload,
            headers={"Authorization": "Bearer test", "X-Request-ID": request_id.upper()},
        )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert runtime.complete.await_args.kwargs["request_id"] == request_id


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["not-a-uuid"],
        ["a" * 4096],
        ["00000000-0000-0000-0000-000000000000"],
        ["123e4567e89b42d3a456426614174000"],
        ["123e4567-e89b-42d3-a456-426614174000,123e4567-e89b-42d3-a456-426614174001"],
        ["123e4567-e89b-42d3-a456-426614174000", "123e4567-e89b-42d3-a456-426614174001"],
    ],
)
async def test_absent_invalid_or_ambiguous_http_id_generates_one_server_id(app_setup, values):
    app, _, runtime, _, _ = app_setup
    runtime.complete = AsyncMock(return_value={"synthetic": True})
    headers = [("Authorization", "Bearer test"), *(("X-Request-ID", value) for value in values)]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers=headers,
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "synthetic"}]},
        )
    actual = response.headers["X-Request-ID"]
    assert response.status_code == 200 and str(UUID(actual)) == actual and UUID(actual).int != 0
    assert actual not in values
    assert runtime.complete.await_args.kwargs["request_id"] == actual


@pytest.mark.parametrize("stream", [False, True])
async def test_real_chat_usage_and_response_share_supplied_id(app_setup, stream):
    app, _, _, llm, ledger = app_setup
    llm.continue_stream.set()
    request_id = str(uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test", "X-Request-ID": request_id},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "synthetic"}], "stream": stream},
        )
    assert response.status_code == 200 and response.headers["X-Request-ID"] == request_id
    assert request_id in response.text
    assert ledger.events and all(event.request_id == event.trace_id == request_id for event in ledger.events)
    assert llm.calls == 1


@pytest.mark.parametrize("failure", ["validation", "authentication", "upstream"])
async def test_error_envelope_keeps_id_without_bypassing_auth_or_admission(app_setup, failure):
    app, runtime, _, llm, ledger = app_setup
    request_id = str(uuid4())
    payload = {"model": "bisheng:42", "messages": [{"role": "user", "content": "synthetic"}]}
    if failure == "validation":
        payload["forged"] = 1
    elif failure == "authentication":
        runtime.access.authenticate.side_effect = DshInvalidAccessTokenError()
    else:
        llm.ainvoke = AsyncMock(side_effect=DshUpstreamErrorError())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer test", "X-Request-ID": request_id},
        )
    assert response.status_code == {"validation": 400, "authentication": 401, "upstream": 502}[failure]
    assert response.headers["X-Request-ID"] == response.json()["request_id"] == request_id
    if failure != "upstream":
        assert llm.calls == 0 and ledger.events == []
    else:
        assert all(event.request_id == request_id for event in ledger.events)


@pytest.mark.parametrize(
    "conversation", [None, {"conversation_id": "e2e-unified-id-conversation", "request_kind": "chat"}]
)
def test_pre_header_failure_projects_summary_without_inventing_execution(
    content_safety_engine, content_safety_event, conversation, metering_tables
):
    request_id = str(uuid4())
    raw = output_event(
        content_safety_event,
        gateway_request_id=request_id,
        backend_request_id=request_id,
        conversation=conversation,
        stage_results={"input": "PASSED", "output": "ERROR"},
        drain_status="NOT_REQUIRED",
    )
    fact, row, _ = committed_merge(content_safety_engine, projection_port(), raw)
    assert fact.association_status == "ASSOCIATED" and fact.audit_request_id == request_id
    assert row.request_id == request_id
    assert row.association_status == ("ASSOCIATED" if conversation else "UNASSOCIATED")
    assert_external_unknowns(row)
    assert row.model_entered is None
    with tenant_session(content_safety_engine) as session:
        assert len(session.exec(select(DshModelAuditRequest)).all()) == 1
        assert session.exec(select(DshModelCall)).all() == []


@pytest.mark.parametrize("reason", ["request_already_started", "request_conflict"])
async def test_supplied_id_does_not_override_existing_admission_rejection(app_setup, reason):
    app, _, _, llm, ledger = app_setup
    request_id = str(uuid4())
    ledger.check_and_start = AsyncMock(side_effect=QuotaRejected(reason))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://example.test") as client:
        response = await client.post(
            "/api/v1/dsh/chat/completions",
            headers={"Authorization": "Bearer test", "X-Request-ID": request_id},
            json={"model": "bisheng:42", "messages": [{"role": "user", "content": "synthetic"}]},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quota_unavailable"
    assert response.json()["request_id"] == response.headers["X-Request-ID"] == request_id
    assert ledger.check_and_start.await_args.args[0].request_id == request_id
    assert llm.calls == 0 and ledger.events == []

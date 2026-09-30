"""F073 endpoints through the real v2 admission pipeline (spec AC-01, AC-03, AC-09).

Only the credential lookup and the business services are faked; routing,
scope markers, request dispatch and the v2 exception handlers are real.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient

from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_api.domain.schemas.task_mode import OpenTaskStatus, OpenTaskSubmitted, OpenTaskView
from bisheng.open_endpoints.api.endpoints import workstation as endpoints
from test.open_api.task_mode_support import sa_principal

TASK_BODY = {
    "run_mode": "task",
    "execution": "async",
    "clientTimestamp": "2026-09-30T10:00:00",
    "text": "Review the contracts",
    "model": "7",
}
DAILY_BODY = {"clientTimestamp": "2026-09-30T10:00:00", "model": "7", "text": "hi"}


@pytest.fixture
def calls(monkeypatch):
    record = SimpleNamespace(principal=sa_principal(), submitted=None, daily=None, config=None)

    async def _validate_bearer(*_args, **_kwargs):
        return record.principal

    async def _submit(principal, req, operator):
        record.submitted = req
        return OpenTaskSubmitted(task_id="svid-1", status=OpenTaskStatus.QUEUED, queue_position=2)

    async def _prepare(**kwargs):
        record.daily = kwargs["request"]
        return SimpleNamespace(), SimpleNamespace()

    async def _stream(*_args, **_kwargs):
        return PlainTextResponse("data: daily\n\n", media_type="text/event-stream")

    async def _task_config(principal, operator):
        record.config = "task"
        return {"models": [], "default_model_id": None, "tools": [], "skills": []}

    async def _daily_config(operator):
        record.config = "daily"
        return {"models": [], "tools": []}

    view = OpenTaskView(task_id="svid-1", status=OpenTaskStatus.RUNNING)
    monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", _validate_bearer)
    monkeypatch.setattr(endpoints, "get_open_api_operator_async", AsyncMock(return_value=SimpleNamespace(user_id=12)))
    monkeypatch.setattr(endpoints.OpenTaskModeService, "submit", _submit)
    monkeypatch.setattr(endpoints.OpenTaskModeService, "task_config", _task_config)
    monkeypatch.setattr(endpoints.OpenTaskModeService, "get_view", AsyncMock(return_value=view))
    monkeypatch.setattr(endpoints.OpenTaskModeService, "terminate", AsyncMock(return_value=view))
    monkeypatch.setattr(
        endpoints.OpenTaskModeService, "download", AsyncMock(return_value=PlainTextResponse("file-bytes"))
    )
    monkeypatch.setattr(endpoints.OpenDailyChatService, "prepare_request", _prepare)
    monkeypatch.setattr(endpoints, "stream_chat_completion", _stream)
    monkeypatch.setattr(endpoints.WorkStationService, "get_open_api_daily_config", _daily_config)
    return record


@pytest.fixture
def app():
    application = FastAPI()
    register_open_api_exception_handlers(application)
    v2 = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
    v2.include_router(endpoints.router)
    application.include_router(v2)
    return application


async def _post(app, path, body):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=body, headers={"Authorization": "Bearer bs-sak-test"})


async def _get(app, path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": "Bearer bs-sak-test"})


async def test_task_submission_returns_json_with_the_task_id(app, calls):
    response = await _post(app, "/api/v2/workstation/chat/completions", TASK_BODY)
    assert response.status_code == 200
    assert response.json()["data"] == {"task_id": "svid-1", "status": "queued", "queue_position": 2}
    assert calls.submitted.text == "Review the contracts"


@pytest.mark.parametrize(
    "overrides,http_status,code",
    [
        ({"execution": None}, 400, 26060),
        ({"execution": "sync"}, 400, 26060),
        ({"conversationId": "chat-1"}, 400, 26061),
        ({"use_knowledge_base": {"personal_knowledge_enabled": True}}, 400, 400),
        ({"text": ""}, 400, 400),
        ({"run_mode": "research"}, 400, 26017),
    ],
)
async def test_task_body_rejections(app, calls, overrides, http_status, code):
    body = {**TASK_BODY, **overrides}
    body = {k: v for k, v in body.items() if v is not None}
    response = await _post(app, "/api/v2/workstation/chat/completions", body)
    assert (response.status_code, response.json()["status_code"]) == (http_status, code)
    assert calls.submitted is None


async def test_run_mode_sync_task_and_daily_async_are_distinguishable(app, calls):
    task_sync = await _post(app, "/api/v2/workstation/chat/completions", {**TASK_BODY, "execution": "sync"})
    daily_async = await _post(app, "/api/v2/workstation/chat/completions", {**DAILY_BODY, "execution": "async"})
    unknown = await _post(app, "/api/v2/workstation/chat/completions", {**DAILY_BODY, "run_mode": "x"})
    codes = {task_sync.json()["status_code"], daily_async.json()["status_code"], unknown.json()["status_code"]}
    assert codes == {26060, 26015, 26017}


async def test_daily_mode_is_unchanged(app, calls):
    response = await _post(app, "/api/v2/workstation/chat/completions", DAILY_BODY)
    assert response.status_code == 200
    assert response.text == "data: daily\n\n"
    assert calls.daily.model == "7"
    assert calls.submitted is None


async def test_daily_validation_error_keeps_fastapi_shape(app, calls):
    response = await _post(app, "/api/v2/workstation/chat/completions", {"model": "7"})
    assert response.status_code == 400
    (error,) = response.json()["status_message"]
    assert error["loc"] == ["body", "clientTimestamp"]
    assert error["type"] == "missing"
    assert "url" not in error


@pytest.mark.parametrize(
    "query,expected",
    [("", "daily"), ("?run_mode=daily", "daily"), ("?run_mode=task", "task")],
)
async def test_config_dispatches_on_run_mode(app, calls, query, expected):
    response = await _get(app, f"/api/v2/workstation/config{query}")
    assert response.status_code == 200
    assert calls.config == expected


async def test_config_rejects_an_unknown_run_mode(app, calls):
    response = await _get(app, "/api/v2/workstation/config?run_mode=research")
    assert (response.status_code, response.json()["status_code"]) == (400, 26017)


async def test_task_resource_endpoints(app, calls):
    view = await _get(app, "/api/v2/workstation/tasks/svid-1")
    assert view.status_code == 200 and view.json()["data"]["status"] == "running"
    stopped = await _post(app, "/api/v2/workstation/tasks/svid-1/terminate", None)
    assert stopped.status_code == 200
    downloaded = await _get(app, "/api/v2/workstation/tasks/svid-1/files/f1")
    assert downloaded.text == "file-bytes"


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v2/workstation/chat/completions", "post"),
        ("/api/v2/workstation/tasks/svid-1", "get"),
        ("/api/v2/workstation/config?run_mode=task", "get"),
    ],
)
async def test_missing_chat_invoke_is_403(app, calls, path, method):
    calls.principal = sa_principal().model_copy(update={"scopes": frozenset({"knowledge:read"})})
    response = await (_post(app, path, TASK_BODY) if method == "post" else _get(app, path))
    assert (response.status_code, response.json()["status_code"]) == (403, 26003)
    assert calls.submitted is None


async def test_personal_access_token_cannot_reach_task_mode(app, calls, monkeypatch):
    # PAT capability switched on at both layers, so the scope check is what rejects it.
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.settings", SimpleNamespace(open_api=SimpleNamespace(pat_enabled=True))
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.TenantSettingService.get_policy",
        AsyncMock(return_value=SimpleNamespace(enabled=True, data_scope="all_visible")),
    )
    calls.principal = sa_principal().model_copy(
        update={
            "actor_kind": "natural_person",
            "authorization_subject_type": "user",
            "authorization_subject_id": 12,
            "effective_user_id": 12,
            "scopes": frozenset({"knowledge:read"}),  # the only scope a PAT can hold
        }
    )
    response = await _post(app, "/api/v2/workstation/chat/completions", TASK_BODY)
    assert (response.status_code, response.json()["status_code"]) == (403, 26003)
    assert calls.submitted is None

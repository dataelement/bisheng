from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncDisabledError
from bisheng.common.errcode.filelib_sync import FilelibSyncError
from bisheng.common.schemas.api import PageData
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncConfig,
    AutomotiveSheetIntroSyncRunRead,
    AutomotiveSheetIntroSyncTestResponse,
)

ENDPOINT_MOD = "bisheng.developer_token.api.endpoints.automotive_sheet_intro_sync"
BASE_PATH = "/api/v1/admin/developer-tokens/automotive-sheet-intro-sync"


def _user(*, tenant_id: int = 5) -> MagicMock:
    user = MagicMock(spec=UserPayload)
    user.user_id = 100
    user.tenant_id = tenant_id
    return user


def _handle_filelib_sync_error(_: object, exc: Exception) -> ORJSONResponse:
    if isinstance(exc, FilelibSyncError):
        return ORJSONResponse(
            status_code=exc.http_status,
            content=exc.http_response_payload(),
        )
    raise exc


def _app(login_user: MagicMock) -> FastAPI:
    from bisheng.admin.api.router import router as admin_router

    app = FastAPI()
    app.add_exception_handler(FilelibSyncError, _handle_filelib_sync_error)
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user
    return app


def _enabled_config() -> AutomotiveSheetIntroSyncConfig:
    return AutomotiveSheetIntroSyncConfig.model_validate(
        {
            "enabled": True,
            "api_url": "https://example.com/automotive.pdf",
            "developer_token_id": 10,
        }
    )


def _run_read() -> AutomotiveSheetIntroSyncRunRead:
    return AutomotiveSheetIntroSyncRunRead(
        id=1,
        job_code="automotive_sheet_intro",
        trigger_type="manual",
        status="success",
        file_id=900,
        knowledge_id=100,
        file_name="汽车板介绍.pdf",
        start_time=datetime(2026, 7, 28, 0, 0, 0),
        end_time=datetime(2026, 7, 28, 0, 0, 5),
        duration_ms=5000,
    )


def test_get_config_returns_current_tenant_config():
    app = _app(_user())
    client = TestClient(app)
    config = _enabled_config()
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.get_config",
        new=AsyncMock(return_value=config),
    ):
        resp = client.get(BASE_PATH)

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["enabled"] is True
    assert body["api_url"] == "https://example.com/automotive.pdf"


def test_put_config_round_trips_saved_payload():
    app = _app(_user())
    client = TestClient(app)
    payload = _enabled_config().model_dump(mode="json")
    saved = _enabled_config()
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.save_config",
        new=AsyncMock(return_value=saved),
    ) as save_mock:
        resp = client.put(BASE_PATH, json=payload)

    assert resp.status_code == 200
    assert resp.json()["data"]["developer_token_id"] == 10
    save_mock.assert_awaited_once()
    assert save_mock.await_args.args[1].enabled is True


def test_post_test_returns_403_when_disabled():
    app = _app(_user())
    client = TestClient(app)
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.trigger_test",
        new=AsyncMock(side_effect=AutomotiveSheetIntroSyncDisabledError()),
    ):
        resp = client.post(f"{BASE_PATH}/test")

    assert resp.status_code == 403
    body = resp.json()
    assert body["status_code"] == 403
    assert body["data"]["error_code"] == 19907


def test_post_test_returns_run_result():
    app = _app(_user())
    client = TestClient(app)
    response = AutomotiveSheetIntroSyncTestResponse(
        run_id=11,
        status="success",
        file_id=900,
        tenant_id=5,
        message="Automotive sheet intro sync completed successfully",
    )
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.trigger_test",
        new=AsyncMock(return_value=response),
    ):
        resp = client.post(f"{BASE_PATH}/test")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["run_id"] == 11
    assert body["status"] == "success"
    assert body["file_id"] == 900
    assert body["tenant_id"] == 5


def test_get_runs_returns_paginated_history():
    app = _app(_user())
    client = TestClient(app)
    page = PageData(data=[_run_read()], total=1)
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.list_runs",
        new=AsyncMock(return_value=page),
    ) as list_mock:
        resp = client.get(f"{BASE_PATH}/runs?page=1&limit=20")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total"] == 1
    assert body["data"][0]["status"] == "success"
    assert body["data"][0]["file_id"] == 900
    list_mock.assert_awaited_once()
    assert list_mock.await_args.kwargs == {"page": 1, "limit": 20}


def test_get_runs_defaults_to_five_per_page():
    app = _app(_user())
    client = TestClient(app)
    page = PageData(data=[], total=0)
    with patch(
        f"{ENDPOINT_MOD}.AutomotiveSheetIntroSyncAdminService.list_runs",
        new=AsyncMock(return_value=page),
    ) as list_mock:
        resp = client.get(f"{BASE_PATH}/runs")

    assert resp.status_code == 200
    list_mock.assert_awaited_once()
    assert list_mock.await_args.kwargs == {"page": 1, "limit": 5}

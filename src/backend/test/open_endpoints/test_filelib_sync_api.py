from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from fastapi.testclient import TestClient

from bisheng.common.errcode.filelib_sync import (
    FilelibSyncConflictError,
    FilelibSyncError,
    FilelibSyncInvalidParamsError,
    FilelibSyncMultipartError,
    FilelibSyncNotFoundError,
    FilelibSyncPermissionDeniedError,
    FilelibSyncRuleNotConfiguredError,
)
from bisheng.open_endpoints.api.dependencies import get_filelib_sync_service
from bisheng.open_endpoints.api.endpoints import filelib_sync as filelib_sync_endpoint
from bisheng.open_endpoints.domain.schemas.filelib_sync import FilelibSyncResponseData

SYNC_PATH = "/api/v2/filelib/file/sync"
DEFAULT_PARAMS = {"external_file_id": "ext-1", "file_name": "report.pdf"}


def _handle_filelib_sync_error(_: Request, exc: Exception) -> ORJSONResponse:
    if isinstance(exc, FilelibSyncError):
        return ORJSONResponse(
            status_code=exc.http_status,
            content=exc.http_response_payload(),
        )
    raise exc


def _build_app(*, service: object | None = None) -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse)
    app.add_exception_handler(FilelibSyncError, _handle_filelib_sync_error)
    app.include_router(filelib_sync_endpoint.router, prefix="/api/v2")

    if service is not None:
        app.dependency_overrides[get_filelib_sync_service] = lambda: service
    return app


def _multipart_files(
    *,
    params: dict | None = DEFAULT_PARAMS,
    filename: str = "report.pdf",
    content: bytes = b"pdf-content",
):
    payload: dict[str, tuple] = {
        "file": (filename, BytesIO(content), "application/pdf"),
    }
    if params is not None:
        payload["params"] = (None, json.dumps(params, ensure_ascii=False))
    return payload


def _success_result(**overrides) -> FilelibSyncResponseData:
    payload = {
        "external_file_id": "ext-1",
        "file_id": 9,
        "file_encoding": "SGGF-POL-IT-20260700000001",
        "knowledge_id": 8,
        "knowledge_name": "信息库",
        "status": 5,
        "version_link_pending": False,
        "replaced_file_id": None,
    }
    payload.update(overrides)
    return FilelibSyncResponseData.model_validate(payload)


def test_openapi_exposes_unified_sync_route():
    app = _build_app(service=SimpleNamespace(sync=AsyncMock()))
    openapi = app.openapi()
    assert SYNC_PATH in openapi["paths"]
    assert "post" in openapi["paths"][SYNC_PATH]


def test_sync_api_success_returns_unified_response():
    service = SimpleNamespace(sync=AsyncMock(return_value=_success_result()))
    with TestClient(_build_app(service=service)) as client:
        response = client.post(SYNC_PATH, files=_multipart_files())

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert body["status_message"] == "SUCCESS"
    assert body["data"] == {
        "external_file_id": "ext-1",
        "file_id": 9,
        "file_encoding": "SGGF-POL-IT-20260700000001",
        "knowledge_id": 8,
        "knowledge_name": "信息库",
        "status": 5,
        "version_link_pending": False,
        "replaced_file_id": None,
    }
    service.sync.assert_awaited_once()


def test_sync_api_success_with_version_link_fields():
    service = SimpleNamespace(
        sync=AsyncMock(
            return_value=_success_result(
                version_link_pending=True,
                replaced_file_id=88,
            )
        )
    )
    with TestClient(_build_app(service=service)) as client:
        response = client.post(SYNC_PATH, files=_multipart_files())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version_link_pending"] is True
    assert data["replaced_file_id"] == 88


def test_sync_api_forwards_raw_params_to_service():
    captured: dict[str, object] = {}

    async def _sync(*, raw_params: str, upload_file):
        captured["raw_params"] = raw_params
        captured["filename"] = upload_file.filename
        return _success_result()

    service = SimpleNamespace(sync=AsyncMock(side_effect=_sync))
    params = {
        **DEFAULT_PARAMS,
        "department_id": "20491061",
        "responsible_person_id": "34",
    }
    with TestClient(_build_app(service=service)) as client:
        response = client.post(SYNC_PATH, files=_multipart_files(params=params))

    assert response.status_code == 200
    assert json.loads(captured["raw_params"]) == params
    assert captured["filename"] == "report.pdf"


@pytest.mark.parametrize(
    ("files", "expected_message"),
    [
        ({}, "multipart form requires file and params"),
        (_multipart_files(params=None), "multipart form requires file and params"),
        ({"params": (None, json.dumps(DEFAULT_PARAMS))}, "multipart form requires file and params"),
    ],
)
def test_sync_api_missing_multipart_parts_return_422(files, expected_message):
    service = SimpleNamespace(sync=AsyncMock())
    with TestClient(_build_app(service=service)) as client:
        response = client.post(SYNC_PATH, files=files)

    assert response.status_code == FilelibSyncMultipartError.HttpStatus
    body = response.json()
    assert body == {
        "status_code": 422,
        "status_message": expected_message,
        "data": {"error_code": 19905},
    }
    service.sync.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "http_status", "error_code", "message"),
    [
        (
            FilelibSyncInvalidParamsError(msg="params must be valid JSON"),
            400,
            19901,
            "params must be valid JSON",
        ),
        (
            FilelibSyncPermissionDeniedError(msg="upload permission denied"),
            403,
            19902,
            "upload permission denied",
        ),
        (
            FilelibSyncNotFoundError(msg="external department mapping does not exist"),
            404,
            19903,
            "external department mapping does not exist",
        ),
        (
            FilelibSyncConflictError(msg="duplicate file content or name"),
            409,
            19904,
            "duplicate file content or name",
        ),
    ],
)
def test_sync_api_business_errors_return_actual_http_status(error, http_status, error_code, message):
    service = SimpleNamespace(sync=AsyncMock(side_effect=error))
    with TestClient(_build_app(service=service)) as client:
        response = client.post(SYNC_PATH, files=_multipart_files())

    assert response.status_code == http_status
    assert response.json() == {
        "status_code": http_status,
        "status_message": message,
        "data": {"error_code": error_code},
    }


def test_sync_api_rule_not_configured_returns_403_before_service():
    service = SimpleNamespace(sync=AsyncMock())

    async def _reject_service():
        raise FilelibSyncRuleNotConfiguredError()

    app = _build_app()
    app.dependency_overrides[get_filelib_sync_service] = _reject_service

    with TestClient(app) as client:
        response = client.post(SYNC_PATH, files=_multipart_files())

    assert response.status_code == 403
    assert response.json() == {
        "status_code": 403,
        "status_message": "filelib_sync_rule_not_configured",
        "data": {"error_code": 19906},
    }
    service.sync.assert_not_awaited()


@pytest.mark.parametrize("legacy_code", ["03", "07", "15"])
def test_sync_api_legacy_numbered_routes_are_not_registered(legacy_code):
    service = SimpleNamespace(sync=AsyncMock())
    with TestClient(_build_app(service=service)) as client:
        response = client.post(
            f"{SYNC_PATH}/{legacy_code}",
            files=_multipart_files(),
        )

    assert response.status_code == 404
    service.sync.assert_not_awaited()

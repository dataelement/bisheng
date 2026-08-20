from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.testclient import TestClient

from bisheng.common.errcode.filelib_sync import FilelibSyncError
from bisheng.common.errcode.inspection_standard_sync import InspectionStandardSyncTokenRuleError
from bisheng.open_endpoints.api.dependencies import get_inspection_standard_sync_service
from bisheng.open_endpoints.api.endpoints import filelib_sync as filelib_sync_endpoint
from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import (
    InspectionStandardSyncFileResult,
    InspectionStandardSyncResponseData,
)

INSPECTION_SYNC_PATH = "/api/v2/filelib/inspection-standard/sync"


def _handle_sync_error(_: object, exc: Exception) -> ORJSONResponse:
    if isinstance(exc, FilelibSyncError):
        return ORJSONResponse(
            status_code=exc.http_status,
            content=exc.http_response_payload(),
        )
    raise exc


def _build_app(*, service: object | None = None) -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse)
    app.add_exception_handler(FilelibSyncError, _handle_sync_error)
    app.include_router(filelib_sync_endpoint.router, prefix="/api/v2")
    if service is not None:
        app.dependency_overrides[get_inspection_standard_sync_service] = lambda: service
    return app


def _success_result() -> InspectionStandardSyncResponseData:
    return InspectionStandardSyncResponseData(
        data_start_time="2026-08-01T00:00:00",
        data_end_time="2026-08-14T23:59:59",
        group_count=1,
        files=[
            InspectionStandardSyncFileResult(
                create_dept_id="DEPT-A",
                external_file_id="INSPECTION-STD-DEPT-A-abc",
                file_id=456,
                file_encoding="ENC-001",
                knowledge_id=118,
                knowledge_name="智能制造室(制造)",
                folder_path="点检标准/DEPT-A/2026",
                generated_file_name="2026-08-01至2026-08-14.xlsx",
                status=5,
                check_standard_count=1,
                check_standard_item_count=1,
            )
        ],
    )


def test_openapi_exposes_inspection_standard_sync_route():
    app = _build_app(service=SimpleNamespace(sync=AsyncMock()))
    openapi = app.openapi()
    assert INSPECTION_SYNC_PATH in openapi["paths"]


def test_inspection_standard_sync_api_success():
    service = SimpleNamespace(sync=AsyncMock(return_value=_success_result()))
    payload = {
        "start_time": "2026-08-01T00:00:00",
        "end_time": "2026-08-14T23:59:59",
        "data": {
            "check_standards": [
                {
                    "CREATE_DEPT_ID": "DEPT-A",
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "DEVICE_NAME": "调度大厅",
                    "STANDARD_TYPE": "01-常规点检",
                    "CHECK_ITEM_NAME": "调度操作台综合检查",
                    "DEVICE_STATUS": "1-运转",
                    "ENFORCE_CODE": "1-点检",
                    "SAFETY_BOARD": "N-否",
                    "CHECK_PERIOD": "1",
                    "PERIOD_UNIT": "W-周",
                    "INTERFACE_SYSTEM": "1-智能点检系统",
                    "NEXT_SCHE_DATE": "2026-05-06",
                    "MAINTAIN_REASON": "初始建立",
                    "DEVICE_MAINTAIN_JOB_ID": "JOB001",
                    "REC_CREATOR": "E001",
                    "REC_CREATOR_NAME": "张三",
                }
            ],
            "check_standard_items": [
                {
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "CHECK_STANDARD_SEQ_NO": "001",
                    "CONTENT": "操作按钮、手柄灵活性及定位",
                    "CHECK_WAY": "1-五感",
                    "LUBRIC_WAY": "0-无",
                    "MANAGE_CONTROL_MODE": "0-无",
                    "DATA_TYPE": "10-定性",
                    "CRITERI": "灵活方便，定位可靠（GB 20905）",
                    "STATUTORY_REQ": "0-无",
                }
            ],
        },
    }

    with TestClient(_build_app(service=service)) as client:
        response = client.post(INSPECTION_SYNC_PATH, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert body["data"]["group_count"] == 1
    assert body["data"]["files"][0]["create_dept_id"] == "DEPT-A"
    service.sync.assert_awaited_once()


def test_inspection_standard_sync_api_accepts_numeric_field_coercion():
    service = SimpleNamespace(sync=AsyncMock(return_value=_success_result()))
    payload = {
        "start_time": "2026-08-01T00:00:00",
        "end_time": "2026-08-14T23:59:59",
        "data": {
            "check_standards": [
                {
                    "CREATE_DEPT_ID": "DEPT-A",
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "DEVICE_NAME": "调度大厅",
                    "STANDARD_TYPE": "01-常规点检",
                    "CHECK_ITEM_NAME": "调度操作台综合检查",
                    "DEVICE_STATUS": "1-运转",
                    "ENFORCE_CODE": "1-点检",
                    "SAFETY_BOARD": "N-否",
                    "CHECK_PERIOD": 1,
                    "PERIOD_UNIT": "W-周",
                    "INTERFACE_SYSTEM": "1-智能点检系统",
                    "NEXT_SCHE_DATE": "2026-05-06",
                    "MAINTAIN_REASON": "初始建立",
                    "DEVICE_MAINTAIN_JOB_ID": "JOB001",
                    "REC_CREATOR": "E001",
                    "REC_CREATOR_NAME": "张三",
                }
            ],
            "check_standard_items": [
                {
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "CHECK_STANDARD_SEQ_NO": "001",
                    "CONTENT": "机房温度",
                    "CHECK_WAY": "2-简易仪器",
                    "LUBRIC_WAY": "0-无",
                    "LUBRIC_POINT": 2,
                    "MANAGE_CONTROL_MODE": "0-无",
                    "DATA_TYPE": "20-定量",
                    "CRITERI": "18-27℃",
                    "UOM": "℃",
                    "QLTY_TOP": 27,
                    "QLTY_BOTTOM": 18,
                    "STATUTORY_REQ": "0-无",
                }
            ],
        },
    }

    with TestClient(_build_app(service=service)) as client:
        response = client.post(INSPECTION_SYNC_PATH, json=payload)

    assert response.status_code == 200
    validated_request = service.sync.await_args.args[0]
    assert validated_request.data.check_standards[0].CHECK_PERIOD == "1"
    assert validated_request.data.check_standard_items[0].LUBRIC_POINT == "2"
    assert validated_request.data.check_standard_items[0].QLTY_TOP == "27"
    assert validated_request.data.check_standard_items[0].QLTY_BOTTOM == "18"


def test_inspection_standard_sync_api_returns_token_rule_error():
    service = SimpleNamespace(
        sync=AsyncMock(
            side_effect=InspectionStandardSyncTokenRuleError(
                msg="token file_sync_rule requires fixed business domain",
            )
        )
    )
    payload = {
        "start_time": "2026-08-01T00:00:00",
        "end_time": "2026-08-14T23:59:59",
        "data": {
            "check_standards": [
                {
                    "CREATE_DEPT_ID": "DEPT-A",
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "DEVICE_NAME": "调度大厅",
                    "STANDARD_TYPE": "01-常规点检",
                    "CHECK_ITEM_NAME": "调度操作台综合检查",
                    "DEVICE_STATUS": "1-运转",
                    "ENFORCE_CODE": "1-点检",
                    "SAFETY_BOARD": "N-否",
                    "CHECK_PERIOD": "1",
                    "PERIOD_UNIT": "W-周",
                    "INTERFACE_SYSTEM": "1-智能点检系统",
                    "NEXT_SCHE_DATE": "2026-05-06",
                    "MAINTAIN_REASON": "初始建立",
                    "DEVICE_MAINTAIN_JOB_ID": "JOB001",
                    "REC_CREATOR": "E001",
                    "REC_CREATOR_NAME": "张三",
                }
            ],
            "check_standard_items": [
                {
                    "CHECK_STANDARD_ID": "270101J01D01",
                    "CHECK_STANDARD_SEQ_NO": "001",
                    "CONTENT": "操作按钮、手柄灵活性及定位",
                    "CHECK_WAY": "1-五感",
                    "LUBRIC_WAY": "0-无",
                    "MANAGE_CONTROL_MODE": "0-无",
                    "DATA_TYPE": "10-定性",
                    "CRITERI": "灵活方便，定位可靠（GB 20905）",
                    "STATUTORY_REQ": "0-无",
                }
            ],
        },
    }

    with TestClient(_build_app(service=service)) as client:
        response = client.post(INSPECTION_SYNC_PATH, json=payload)

    assert response.status_code == 403
    assert response.json()["data"]["error_code"] == 19915

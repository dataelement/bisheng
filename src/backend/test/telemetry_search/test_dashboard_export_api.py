"""T016 — export endpoint HTTP wiring (F058, AC-09, AC-10).

Business logic (permission delegation, empty/limit errors, Excel building) is already
covered at the service layer by test_dashboard_export_service.py. This file only proves
the two new routes bind their path/body params correctly and wrap the response in
resp_200 — so DashboardExportService itself is mocked out, no DB needed.
"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub

from fastapi import FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.telemetry_search.api.endpoints import dashboard as endpoints_module


class MockLoginUser:
    user_id = 1
    user_name = "admin"


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(endpoints_module.router, prefix="/api/v1/telemetry")

    async def get_mock_user():
        return MockLoginUser()

    app.dependency_overrides[UserPayload.get_login_user] = get_mock_user

    export_service = MagicMock()
    export_service.export_component_detail = AsyncMock(return_value="https://minio/detail.xlsx")
    export_service.export_component_all = AsyncMock(return_value="https://minio/all.xlsx")
    monkeypatch.setattr(
        endpoints_module,
        "DashboardExportService",
        MagicMock(return_value=export_service),
    )

    with TestClient(app) as c:
        yield c, export_service


def test_export_detail_endpoint_returns_file_url(client):
    test_client, export_service = client
    resp = test_client.post(
        "/api/v1/telemetry/dashboard/component/comp-1/export",
        json={
            "dashboard_id": 1,
            "dimension_field": "belonging_department_name",
            "dimension_value": "生产制造部",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["data"]["file_url"] == "https://minio/detail.xlsx"

    export_service.export_component_detail.assert_awaited_once()
    call_args = export_service.export_component_detail.call_args.args
    assert call_args[0] == 1  # dashboard_id
    assert call_args[1] == "comp-1"  # component_id (from path)
    assert call_args[2] == "belonging_department_name"
    assert call_args[3] == "生产制造部"


def test_export_all_endpoint_returns_file_url(client):
    test_client, export_service = client
    resp = test_client.post(
        "/api/v1/telemetry/dashboard/component/comp-1/export-all",
        json={"dashboard_id": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["data"]["file_url"] == "https://minio/all.xlsx"

    export_service.export_component_all.assert_awaited_once()
    call_args = export_service.export_component_all.call_args.args
    assert call_args[0] == 1
    assert call_args[1] == "comp-1"

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.finetune.api import finetune
from bisheng.finetune.api.dependencies import get_dataset_user, get_finetune_user


def test_catalog_and_task_uploads_have_separate_menu_gates(monkeypatch):
    app = FastAPI()
    app.include_router(finetune.router, prefix="/api/v1")
    user = SimpleNamespace(user_id=9, user_name="ordinary")
    app.dependency_overrides[get_dataset_user] = lambda: user
    monkeypatch.setattr(finetune.DatasetService, "list_catalog", AsyncMock(return_value={"data": [], "total": 0}))
    with TestClient(app) as client:
        response = client.get("/api/v1/finetune/dataset-catalog?data_type=legacy")
        assert response.status_code == 200 and response.json()["status_code"] == 200
        assert response.json()["data"] == {"data": [], "total": 0}
    routes = {route.path: route for route in app.routes}
    assert get_dataset_user in [
        d.call for d in routes["/api/v1/finetune/dataset-catalog/import"].dependant.dependencies
    ]
    assert get_finetune_user in [d.call for d in routes["/api/v1/finetune/job/file"].dependant.dependencies]

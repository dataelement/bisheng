"""Endpoint-level tests for the 3 similar-document endpoints (Plan 3 T6)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mocked_svc():
    from bisheng.knowledge.api.endpoints.knowledge_version import router
    from bisheng.knowledge.api.dependencies import get_knowledge_version_service

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    svc = MagicMock()
    svc.get_similar_candidates_for_file = AsyncMock(return_value=[])
    svc.list_pending_similar_files = AsyncMock(return_value=[])
    svc.dismiss_similar = AsyncMock(return_value={"knowledge_file_id": 1, "similar_status": 2})

    app.dependency_overrides[get_knowledge_version_service] = lambda: svc
    return app, svc


def test_get_similar_candidates_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.get("/api/v1/knowledge/space/file/42/similar")
    assert r.status_code == 200
    svc.get_similar_candidates_for_file.assert_awaited_once_with(42)


def test_list_similar_pending_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.get("/api/v1/knowledge/space/7/similar-pending")
    assert r.status_code == 200
    svc.list_pending_similar_files.assert_awaited_once_with(7)


def test_dismiss_similar_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.post("/api/v1/knowledge/space/file/42/dismiss-similar")
    assert r.status_code == 200
    svc.dismiss_similar.assert_awaited_once_with(42)

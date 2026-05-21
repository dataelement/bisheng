"""Endpoint-level tests for knowledge_version.py.

These tests build the router directly with a mocked service to validate the URL paths,
HTTP methods, and request/response wiring — without spinning up the full FastAPI app.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mocked_svc():
    """Build a minimal FastAPI app mounting only the knowledge_version router,
    with the KnowledgeVersionService dependency replaced by a MagicMock."""
    from bisheng.knowledge.api.endpoints.knowledge_version import router
    from bisheng.knowledge.api.dependencies import get_knowledge_version_service

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    svc = MagicMock()
    svc.list_versions_for_file = AsyncMock(return_value={"document_id": 1, "knowledge_id": 1,
                                                          "title": "t", "doc_code": None,
                                                          "current_primary_version_no": 1, "versions": []})
    svc.search_associable_documents = AsyncMock(return_value=[])
    svc.link_file_to_document = AsyncMock(return_value={"document_id": 2, "new_version_no": 3})
    svc.set_primary_version = AsyncMock(return_value={"document_id": 2, "new_primary_version_no": 2})
    svc.delete_version = AsyncMock(return_value={"document_id": 2, "deleted_version_no": 1})

    app.dependency_overrides[get_knowledge_version_service] = lambda: svc
    return app, svc


def test_list_versions_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.get("/api/v1/knowledge/space/file/42/versions")
    assert r.status_code == 200
    svc.list_versions_for_file.assert_awaited_once_with(42)


def test_link_document_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.post("/api/v1/knowledge/space/document/link",
                    json={"knowledge_file_id": 100, "target_document_id": 7})
    assert r.status_code == 200
    svc.link_file_to_document.assert_awaited_once_with(
        knowledge_file_id=100, target_document_id=7,
    )


def test_set_primary_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.post("/api/v1/knowledge/space/version/55/set-primary")
    assert r.status_code == 200
    svc.set_primary_version.assert_awaited_once_with(55)


def test_delete_version_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.delete("/api/v1/knowledge/space/version/77")
    assert r.status_code == 200
    svc.delete_version.assert_awaited_once_with(77)


def test_search_documents_endpoint(app_with_mocked_svc):
    app, svc = app_with_mocked_svc
    client = TestClient(app)
    r = client.get("/api/v1/knowledge/space/3/document/search",
                   params={"keyword": "abc", "current_file_id": 100})
    assert r.status_code == 200
    svc.search_associable_documents.assert_awaited_once_with(
        knowledge_id=3, keyword="abc", current_file_id=100,
    )

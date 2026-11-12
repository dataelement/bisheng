"""HTTP-level preview security and upload/preview contract with isolated I/O."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.api.endpoints import knowledge as endpoint
from bisheng.knowledge.domain.services import preview_source_service as sources


@pytest.fixture
def harness(monkeypatch):
    records = {}

    async def aset(key, value, **kwargs):
        records[key] = value

    async def aget(key):
        return records.get(key)

    redis = SimpleNamespace(aset=AsyncMock(side_effect=aset), aget=AsyncMock(side_effect=aget), aexpire_key=AsyncMock())
    user = SimpleNamespace(user_id=7, tenant_id=2)
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    monkeypatch.setattr(endpoint, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(endpoint, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(sources, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.get_redis_client", AsyncMock(return_value=redis)
    )
    monkeypatch.setattr(sources, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(sources, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(tmp_bucket="temporary")))
    monkeypatch.setattr(
        endpoint.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=3, user_id=7, type=1))
    )
    permission = AsyncMock()
    monkeypatch.setattr(endpoint.KnowledgeService.permission_service, "ensure_knowledge_write_async", permission)
    return app, records, permission


async def _status(client, response):
    assert response.status_code == 200, response.text
    preview_id = response.json()["data"]["preview_file_id"]
    status = await client.get("/knowledge/preview/status", params={"preview_file_id": preview_id})
    assert status.status_code == 200
    return status.json()["data"]


async def test_arbitrary_url_is_rejected_in_background_without_network_request(harness, monkeypatch):
    app, _, permission = harness
    network = Mock(side_effect=AssertionError("untrusted URL must not be fetched"))
    monkeypatch.setattr("requests.get", network)
    storage = Mock(side_effect=AssertionError("unauthorized source must not be downloaded"))
    monkeypatch.setattr("bisheng.knowledge.domain.services.knowledge_service.get_minio_storage_sync", storage)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/knowledge/preview",
            json={"knowledge_id": 3, "file_list": [{"file_path": "http://169.254.169.254/latest/meta-data"}]},
        )
        status = await _status(client, response)
    assert status["status"] == "error"
    permission.assert_awaited_once()
    network.assert_not_called()
    storage.assert_not_called()


async def test_background_write_permission_denial_prevents_source_access(harness, monkeypatch):
    app, _, permission = harness
    permission.side_effect = PermissionError("denied")
    resolve = AsyncMock(side_effect=AssertionError("source resolution must not run"))
    monkeypatch.setattr(sources.PreviewSourceService, "resolve", resolve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/knowledge/preview",
            json={"knowledge_id": 3, "file_list": [{"file_path": "issued", "preview_upload_ref": "ref"}]},
        )
        status = await _status(client, response)
    assert status["status"] == "error"
    permission.assert_awaited_once()
    resolve.assert_not_awaited()


async def test_upload_response_reference_is_accepted_by_preview(harness, monkeypatch):
    app, _, permission = harness
    monkeypatch.setattr(endpoint.QuotaService, "check_quota", AsyncMock())
    monkeypatch.setattr(endpoint, "validate_knowledge_upload_file_size", Mock())
    monkeypatch.setattr(
        endpoint.KnowledgeService, "save_upload_file_original_name", AsyncMock(return_value="server-generated.txt")
    )
    monkeypatch.setattr(endpoint, "save_uploaded_file", AsyncMock(return_value="https://storage.invalid/temp"))
    monkeypatch.setattr(endpoint.KnowledgeFileDao, "get_repeat_file", AsyncMock(return_value=None))
    from bisheng.core.cache import utils as cache_utils
    from bisheng.knowledge.domain.services import knowledge_service as service
    from bisheng.knowledge.rag import preview_file_pipeline

    monkeypatch.setattr(
        endpoint.KnowledgeService, "legacy_preview_cache_key", Mock(return_value="legacy"), raising=False
    )
    monkeypatch.setattr(endpoint.KnowledgeService, "async_save_preview_cache", AsyncMock(), raising=False)
    monkeypatch.setattr(endpoint.KnowledgeService, "async_bind_preview_cache_key", AsyncMock(), raising=False)
    response_stream = SimpleNamespace(close=Mock(), release_conn=Mock())
    storage = SimpleNamespace(download_object_sync=Mock(return_value=response_stream))
    monkeypatch.setattr(service, "get_minio_storage_sync", Mock(return_value=storage))
    monkeypatch.setattr(
        service, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(clear_minio_share_host=lambda url: url))
    )
    monkeypatch.setattr(cache_utils, "save_download_file", Mock(return_value="/tmp/server-generated.txt"))
    pipeline = SimpleNamespace(
        loader=None,
        arun=AsyncMock(return_value=SimpleNamespace(documents=[SimpleNamespace(page_content="hello", metadata={})])),
    )
    monkeypatch.setattr(preview_file_pipeline, "PreviewFilePipeline", Mock(return_value=pipeline))
    network = Mock(side_effect=AssertionError("must not fetch an upload URL"))
    monkeypatch.setattr("requests.get", network)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        upload = await client.post("/knowledge/upload/3", files={"file": ("document.txt", b"hello", "text/plain")})
        assert upload.status_code == 200, upload.text
        data = upload.json()["data"]
        assert data["preview_upload_ref"]
        response = await client.post(
            "/knowledge/preview",
            json={
                "knowledge_id": 3,
                "cache": False,
                "file_list": [{"file_path": data["file_path"], "preview_upload_ref": data["preview_upload_ref"]}],
            },
        )
        status = await _status(client, response)
    assert status["status"] == "completed", status
    assert status["data"]["chunks"][0]["text"] == "hello"
    assert permission.await_count == 2
    storage.download_object_sync.assert_called_once_with("temporary", "server-generated.txt")
    response_stream.close.assert_called_once()
    response_stream.release_conn.assert_called_once()
    network.assert_not_called()

"""Security contract for web knowledge ingestion sources."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.api.endpoints import knowledge as endpoint
from bisheng.knowledge.domain.services import knowledge_service as service


@pytest.mark.parametrize("path", ["http://169.254.169.254/latest", "/etc/passwd", "http://minio/temporary/other"])
async def test_process_rejects_unissued_paths_before_any_download(path, monkeypatch):
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7, tenant_id=2)
    monkeypatch.setattr(endpoint.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    download = Mock(side_effect=AssertionError("untrusted source downloaded"))
    monkeypatch.setattr(service, "file_download", download)
    monkeypatch.setattr(
        service.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=3, user_id=7, tenant_id=2))
    )
    monkeypatch.setattr(service.KnowledgeService.permission_service, "ensure_knowledge_write_async", AsyncMock())
    monkeypatch.setattr(service.KnowledgeService, "ensure_knowledge_upload_tenant_consistency", Mock())
    monkeypatch.setattr(service.KnowledgeFileDao, "aget_user_upload_total_file_size", AsyncMock(return_value=0))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/knowledge/process", json={"knowledge_id": 3, "file_list": [{"file_path": path}]})
    assert response.status_code in (400, 403, 404, 422)
    download.assert_not_called()


async def test_batch_rejects_invalid_ref_before_processing_valid_ref(monkeypatch):
    from bisheng.knowledge.domain.services import preview_source_service as sources

    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(user_id=7, tenant_id=2)
    monkeypatch.setattr(endpoint.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=3, user_id=7, tenant_id=2))
    )
    monkeypatch.setattr(service.KnowledgeService.permission_service, "ensure_knowledge_write_async", AsyncMock())
    monkeypatch.setattr(service.KnowledgeService, "ensure_knowledge_upload_tenant_consistency", Mock())
    monkeypatch.setattr(sources, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(sources, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp")))
    redis = SimpleNamespace(
        aget=AsyncMock(
            side_effect=[
                {
                    "user_id": 7,
                    "tenant_id": 2,
                    "knowledge_id": 3,
                    "file_path": "issued",
                    "file_name": "a.txt",
                    "object_name": "server.txt",
                },
                None,
            ]
        )
    )
    monkeypatch.setattr(sources, "get_redis_client", AsyncMock(return_value=redis))
    process = Mock(side_effect=AssertionError("must validate entire batch"))
    monkeypatch.setattr(service.KnowledgeService, "process_one_file", process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/knowledge/process",
            json={
                "knowledge_id": 3,
                "file_list": [
                    {"file_path": "issued", "preview_upload_ref": "valid"},
                    {"file_path": "bad", "preview_upload_ref": "invalid"},
                ],
            },
        )
    assert response.status_code == 404
    process.assert_not_called()


def test_trusted_process_downloads_only_resolved_object_and_keeps_duplicate_lifecycle(monkeypatch, tmp_path):
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSource
    from bisheng.api.v1.schemas import KnowledgeFileOne
    from bisheng.core.cache import utils

    path = tmp_path / "content.txt"
    path.write_text("content")
    stream = SimpleNamespace(close=Mock(), release_conn=Mock())
    minio = SimpleNamespace(download_object_sync=Mock(return_value=stream), put_object_tmp_sync=Mock())
    monkeypatch.setattr(service, "get_minio_storage_sync", Mock(return_value=minio))
    monkeypatch.setattr(utils, "save_download_file", Mock(return_value=str(path)))
    monkeypatch.setattr(service, "file_download", Mock(side_effect=AssertionError("URL download forbidden")))
    duplicate = SimpleNamespace(id=12, md5="content", file_name="a.txt")
    monkeypatch.setattr(service.KnowledgeFileDao, "get_file_by_condition", Mock(return_value=[duplicate]))
    monkeypatch.setattr(service.KnowledgeService, "get_upload_file_original_name", Mock(return_value="a.txt"))
    monkeypatch.setattr(
        service.KnowledgeService, "remove_unused_file", Mock(side_effect=AssertionError("untrusted cleanup"))
    )
    source = PreviewSource("temporary", "server.txt", "a.txt", "issued", "issued")
    result = service.KnowledgeService.process_one_file(
        SimpleNamespace(),
        SimpleNamespace(id=3),
        KnowledgeFileOne(file_path="issued", preview_upload_ref="ref"),
        {},
        trusted_source=source,
    )
    assert result is duplicate
    minio.download_object_sync.assert_called_once_with("temporary", "server.txt")
    minio.put_object_tmp_sync.assert_called_once()
    stream.close.assert_called_once()
    stream.release_conn.assert_called_once()


async def test_process_preserves_issued_url_as_preview_cache_key(monkeypatch):
    from bisheng.api.v1.schemas import KnowledgeFileProcess
    from bisheng.knowledge.domain.services import preview_source_service as sources

    user = SimpleNamespace(user_id=7, tenant_id=2)
    knowledge = SimpleNamespace(id=3, user_id=7, tenant_id=2)
    req = KnowledgeFileProcess(knowledge_id=3, file_list=[{"file_path": "issued-url", "preview_upload_ref": "ref"}])
    monkeypatch.setattr(service.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=knowledge))
    monkeypatch.setattr(service.KnowledgeService.permission_service, "ensure_knowledge_write_async", AsyncMock())
    monkeypatch.setattr(service.KnowledgeService, "ensure_knowledge_upload_tenant_consistency", Mock())
    monkeypatch.setattr(service.KnowledgeFileDao, "aget_user_upload_total_file_size", AsyncMock(return_value=0))
    source = sources.PreviewSource("temporary", "server.txt", "a.txt", "issued-url", "issued-url")
    monkeypatch.setattr(sources.PreviewSourceService, "resolve", AsyncMock(return_value=source))
    db_file = SimpleNamespace(id=5, status=2, file_size=1)
    process = Mock(return_value=db_file)
    monkeypatch.setattr(service.KnowledgeService, "process_one_file", process)
    cache = Mock(return_value="cache-key")
    monkeypatch.setattr(service.KnowledgeService, "preview_cache_key_for_split_rule", cache)
    _, failed, processed, keys = await service.KnowledgeService.asave_knowledge_file(
        user, req, trusted_uploads_only=True
    )
    assert failed == [] and processed == [db_file] and keys == ["cache-key"]
    assert cache.call_args.args[1] == "issued-url"
    assert process.call_args.kwargs["trusted_source"] is source
    assert cache.call_args.args[2]["excel_rule"] == service.ExcelRule().model_dump()


def test_trusted_new_file_uses_server_object(monkeypatch, tmp_path):
    from bisheng.api.v1.schemas import KnowledgeFileOne
    from bisheng.core.cache import utils
    from bisheng.knowledge.domain.services.preview_source_service import PreviewSource

    path = tmp_path / "content.txt"
    path.write_text("content")
    stream = SimpleNamespace(close=Mock(), release_conn=Mock())
    minio = SimpleNamespace(bucket="permanent", download_object_sync=Mock(return_value=stream), put_object_sync=Mock())
    monkeypatch.setattr(service, "get_minio_storage_sync", Mock(return_value=minio))
    monkeypatch.setattr(utils, "save_download_file", Mock(return_value=str(path)))
    monkeypatch.setattr(service, "file_download", Mock(side_effect=AssertionError("URL download forbidden")))
    monkeypatch.setattr(service.KnowledgeFileDao, "get_file_by_condition", Mock(return_value=[]))
    monkeypatch.setattr(service.KnowledgeService, "get_upload_file_original_name", Mock(return_value="a.txt"))
    monkeypatch.setattr(
        service.KnowledgeService, "remove_unused_file", Mock(side_effect=AssertionError("untrusted cleanup"))
    )

    def add_file(file):
        file.id = 12
        return file

    monkeypatch.setattr(service.KnowledgeFileDao, "add_file", add_file)
    monkeypatch.setattr(service.KnowledgeFileDao, "update", Mock())
    monkeypatch.setattr(service.KnowledgeService.audit_telemetry_service, "telemetry_new_knowledge_file", Mock())
    user = SimpleNamespace(user_id=7, user_name="user")
    knowledge = SimpleNamespace(id=3, tenant_id=2, type=-1)
    source = PreviewSource("temporary", "server.txt", "a.txt", "issued", "issued")
    result = service.KnowledgeService.process_one_file(
        user, knowledge, KnowledgeFileOne(file_path="issued", preview_upload_ref="ref"), {}, trusted_source=source
    )
    assert result.id == 12
    minio.download_object_sync.assert_called_once_with("temporary", "server.txt")
    assert minio.put_object_sync.call_args.kwargs["file"] == str(path)

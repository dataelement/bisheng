from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpacePermissionDeniedError
from bisheng.open_endpoints.api import dependencies
from bisheng.open_endpoints.api.endpoints.filelib import router
from bisheng.open_endpoints.domain.services.filelib_file_source_service import FilelibFileSourceService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import RetrieveSourceLink, RetrieveSourceRef


def _service():
    entry = SimpleNamespace(
        id=12,
        knowledge_id=7,
        tenant_id=1,
        file_type=1,
        entry_type=None,
        reference_document_id=None,
    )
    files = MagicMock()
    files.find_by_id = AsyncMock(return_value=entry)
    knowledge = MagicMock()
    knowledge.find_by_id = AsyncMock(return_value=SimpleNamespace(id=7, type=3, state=1, user_id=8))
    versions = MagicMock()
    versions.find_by_knowledge_file_id = AsyncMock(return_value=None)
    source = MagicMock()
    source.resolve_links = AsyncMock(
        return_value={
            12: RetrieveSourceLink(
                "/bisheng/12.pdf?signature=TEST", "https://files.example.com/bisheng/12.pdf?signature=TEST"
            )
        }
    )
    service = FilelibFileSourceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=8, tenant_id=1),
        file_repository=files,
        knowledge_repository=knowledge,
        document_repository=MagicMock(),
        version_repository=versions,
        source_service=source,
    )
    service.space_service._require_read_permission = AsyncMock()
    service.space_service._get_effective_permission_ids = AsyncMock(return_value={"view_file"})
    return service, entry


async def test_view_only_user_can_get_original_link():
    service, _ = _service()
    result = await service.get_source_url(12)
    assert result.file_id == 12
    assert result.source_full_url.startswith("https://files.example.com/bisheng/12.pdf?")
    service.source_service.resolve_links.assert_awaited_once_with([RetrieveSourceRef(12)])


@pytest.mark.parametrize("denial", ["file", "space", "missing", "folder", "invalid-reference"])
async def test_rejected_file_never_reaches_signer(denial):
    service, entry = _service()
    if denial == "file":
        service.space_service._get_effective_permission_ids.return_value = set()
    elif denial == "space":
        service.space_service._require_read_permission.side_effect = SpacePermissionDeniedError()
    elif denial == "missing":
        service.file_repository.find_by_id.return_value = None
    elif denial == "folder":
        entry.file_type = 0
    else:
        entry.entry_type = "publish"
        entry.reference_document_id = 100
        entry.entry_status = "invalid"
    with pytest.raises((SpacePermissionDeniedError, SpaceFileNotFoundError)):
        await service.get_source_url(12)
    service.source_service.resolve_links.assert_not_awaited()


async def test_reference_uses_resolved_canonical_version():
    service, entry = _service()
    entry.entry_type = "publish"
    entry.entry_status = "active"
    entry.reference_document_id = 100
    for key, value in {
        "object_name": None,
        "preview_file_object_name": None,
        "thumbnails": None,
        "file_size": 0,
        "md5": None,
        "bbox_object_name": "",
        "projection_status": "ready",
        "desired_content_generation": 1,
        "applied_content_generation": 1,
        "desired_entry_generation": 1,
        "applied_entry_generation": 1,
        "allow_download": False,
    }.items():
        setattr(entry, key, value)
    manager = SimpleNamespace(
        id=99, tenant_id=1, knowledge_id=9, entry_type="manager", entry_status="active", reference_document_id=100
    )
    service.file_repository.find_by_id.side_effect = lambda file_id: entry if file_id == 12 else manager
    service.entry_resolver.document_repository.find_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id=100, tenant_id=1, knowledge_id=9, lifecycle_status="active", primary_version_id=101, content_generation=1
        )
    )
    service.entry_resolver.version_repository.find_by_id = AsyncMock(
        return_value=SimpleNamespace(id=101, document_id=100, knowledge_file_id=99)
    )
    await service.get_source_url(12)
    service.source_service.resolve_links.assert_awaited_once_with([RetrieveSourceRef(12, 100, 101)])


def test_http_contract_and_input_validation():
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    service = MagicMock()
    service.get_source_url = AsyncMock(
        return_value={"file_id": 12, "source_full_url": "https://files.example.com/bisheng/12.pdf"}
    )
    app.dependency_overrides[dependencies.get_filelib_file_source_service] = lambda: service
    with TestClient(app) as client:
        result = client.get("/api/v2/filelib/file/source_url", params={"file_id": 12})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["data"]["file_id"] == 12
        for value in [None, "0", "-1", "abc"]:
            params = {} if value is None else {"file_id": value}
            assert client.get("/api/v2/filelib/file/source_url", params=params).status_code == 422
    service.get_source_url.assert_awaited_once_with(12)


def test_token_rejection_precedes_business_service():
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")

    async def denied():
        raise HTTPException(403, "token denied")

    from bisheng.developer_token.api.dependencies import get_developer_token_principal

    app.dependency_overrides[get_developer_token_principal] = denied
    with TestClient(app) as client:
        assert client.get("/api/v2/filelib/file/source_url?file_id=12").status_code == 403


@pytest.mark.parametrize("external_id", [None, "EMP001"])
def test_http_real_service_dependency_keeps_user_context_through_signing(monkeypatch, external_id):
    from bisheng.developer_token.api.dependencies import get_developer_token_principal
    from bisheng.open_endpoints.domain.services import filelib_file_source_service as service_module
    from bisheng.open_endpoints.domain.services import filelib_retrieve_source_service as source_module

    service, entry = _service()
    entry.file_name = "report.pdf"
    entry.object_name = "original/12.pdf"
    service.file_repository.find_by_ids = AsyncMock(return_value=[entry])
    events = []
    user = SimpleNamespace(user_id=8 if external_id else 7, tenant_id=1)

    @asynccontextmanager
    async def use_user(principal, supplied_external_id):
        assert supplied_external_id == external_id
        events.append("enter")
        yield user
        events.append("exit")

    def permissions_factory(*, request, login_user):
        assert login_user is user
        return service.space_service

    async def sign(*args, **kwargs):
        assert events == ["enter"]
        assert kwargs == {"clear_host": False, "expire_days": 7}
        events.append("sign")
        return "http://internal.example:9000/bisheng/original/12.pdf?X-Amz-Signature=TEST"

    storage = MagicMock()
    storage.bucket = "bisheng"
    storage.object_exists = AsyncMock(return_value=True)
    storage.get_share_link = AsyncMock(side_effect=sign)
    storage.clear_minio_share_host.side_effect = lambda url: url.removeprefix("http://internal.example:9000")
    monkeypatch.setattr(dependencies, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(dependencies, "get_filelib_source_origin", AsyncMock(return_value="https://public.example.com"))
    monkeypatch.setattr(service_module, "KnowledgeSpaceService", permissions_factory)
    monkeypatch.setattr(source_module.KnowledgeUtils, "resolve_source_object_name", lambda *args: "original/12.pdf")

    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.dependency_overrides.update(
        {
            get_developer_token_principal: lambda: SimpleNamespace(user=user),
            dependencies.get_filelib_user_context_service: lambda: SimpleNamespace(use_user=use_user),
            dependencies.get_knowledge_file_repository: lambda: service.file_repository,
            dependencies.get_knowledge_repository: lambda: service.knowledge_repository,
            dependencies.get_filelib_knowledge_document_repository: lambda: service.entry_resolver.document_repository,
            dependencies.get_filelib_knowledge_document_version_repository: lambda: (
                service.entry_resolver.version_repository
            ),
        }
    )
    with TestClient(app) as client:
        params = {"file_id": 12}
        if external_id:
            params["external_id"] = external_id
        result = client.get("/api/v2/filelib/file/source_url", params=params)
    assert result.status_code == 200
    assert result.json()["data"] == {
        "file_id": 12,
        "source_full_url": "https://public.example.com/bisheng/original/12.pdf?X-Amz-Signature=TEST",
    }
    assert events == ["enter", "sign", "exit"]


def test_config_save_validates_origin_before_persisting(monkeypatch):
    from bisheng.api.v1 import endpoints
    from bisheng.common.errcode.server import SystemConfigInvalidError

    record = SimpleNamespace(value="old")
    dao = SimpleNamespace(get_config=MagicMock(return_value=record), insert_config=MagicMock())
    cache = MagicMock()
    monkeypatch.setattr(endpoints, "ConfigDao", dao)
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    with pytest.raises(SystemConfigInvalidError):
        endpoints.save_config(
            {"data": "shougang:\n  portal_base_url: https://files.example.com/workspace\n"}, admin_user=object()
        )
    dao.insert_config.assert_not_called()
    assert record.value == "old"
    payload = "shougang:\n  portal_base_url: https://files.example.com:9443\n"
    endpoints.save_config({"data": payload}, admin_user=object())
    assert record.value == payload
    dao.insert_config.assert_called_once_with(record)
    cache.delete.assert_called_once_with("config:initdb_config")

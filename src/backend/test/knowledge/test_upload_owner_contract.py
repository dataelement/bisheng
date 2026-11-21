"""Execute upload writers against real ownership/reference protocol boundaries."""

import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from bisheng.knowledge.api.endpoints import knowledge as endpoint
from bisheng.knowledge.domain.services import preview_source_service as preview
from bisheng.workstation.domain.services.media_cover_service import WorkstationMediaCoverService


@pytest.fixture
def upload_tenant(tenant_context):
    tenant_context(3)


@pytest.mark.parametrize("scope", [0, 11])
async def test_upload_issues_exact_owner_bound_source(monkeypatch, upload_tenant, scope):
    from bisheng.knowledge.domain import upload_file_size

    monkeypatch.setattr(upload_file_size, "settings", SimpleNamespace(get_from_db=lambda key: {}))
    actor = SimpleNamespace(user_id=7, tenant_id=3)
    records = {}

    async def store(key, value, **kwargs):
        records[key] = value

    redis = SimpleNamespace(aset=AsyncMock(side_effect=store), aget=AsyncMock(side_effect=lambda key: records.get(key)))
    storage = SimpleNamespace(tmp_bucket="temporary")
    monkeypatch.setattr(preview, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(preview, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=storage))
    saved = AsyncMock(return_value="opaque-path")
    monkeypatch.setattr(endpoint, "save_uploaded_file", saved)
    monkeypatch.setattr(WorkstationMediaCoverService, "cover_for_uploaded_video", AsyncMock(return_value=None))
    monkeypatch.setattr(
        endpoint.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=11, tenant_id=3, type=3))
    )
    permission = AsyncMock(side_effect=AssertionError("Space staging must not demand library edit"))
    monkeypatch.setattr(endpoint.KnowledgeService.permission_service, "ensure_knowledge_write_async", permission)
    monkeypatch.setattr(endpoint.KnowledgeFileDao, "get_repeat_file", AsyncMock(return_value=None))
    file = UploadFile(filename="../../folder\\qa.xlsx", file=BytesIO(b"qa"), size=2)
    if scope:
        result = await inspect.unwrap(endpoint.upload_knowledge_file)(
            request=Request({"type": "http"}), login_user=actor, knowledge_id=scope, file=file
        )
    else:
        result = await endpoint.upload_file(login_user=actor, file=file)
    key = saved.await_args.args[2]
    assert key.startswith("uploads/3/7/") and key.endswith(".xlsx")
    assert "qa.xlsx" not in key
    assert result.data.file_name == "qa.xlsx"
    assert await preview.PreviewSourceService.is_owned_object(bucket="temporary", object_name=key, login_user=actor)
    item = SimpleNamespace(
        preview_upload_ref=result.data.preview_upload_ref, preview_file_id=None, file_path="opaque-path"
    )
    source = await preview.PreviewSourceService.resolve(item=item, login_user=actor, knowledge_id=scope)
    assert source.object_name == key
    for other in (SimpleNamespace(user_id=8, tenant_id=3),):
        with pytest.raises(HTTPException):
            await preview.PreviewSourceService.resolve(item=item, login_user=other, knowledge_id=scope)
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(4)
    try:
        with pytest.raises(HTTPException):
            await preview.PreviewSourceService.resolve(item=item, login_user=actor, knowledge_id=scope)
    finally:
        current_tenant_id.reset(token)
    permission.assert_not_awaited()

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from bisheng.api.v1.schemas import KnowledgeFileOne
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

MODULE = "bisheng.knowledge.domain.services.preview_source_service"


@pytest.mark.parametrize("changed", ["user_id", "tenant_id", "knowledge_id", "file_path"])
async def test_upload_reference_rejects_wrong_binding(changed):
    record = {
        "user_id": 7,
        "tenant_id": 2,
        "knowledge_id": 3,
        "object_name": "random.pdf",
        "file_path": "issued",
        "file_name": "a.pdf",
    }
    record[changed] = "wrong"
    item = KnowledgeFileOne(file_path="issued", preview_upload_ref="token")
    redis = SimpleNamespace(aget=AsyncMock(return_value=record))
    with (
        patch(f"{MODULE}.get_current_tenant_id", return_value=2),
        patch(f"{MODULE}.get_minio_storage", AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp"))),
        patch(f"{MODULE}.get_redis_client", AsyncMock(return_value=redis)),
    ):
        with pytest.raises(HTTPException):
            await PreviewSourceService.resolve(item=item, login_user=SimpleNamespace(user_id=7), knowledge_id=3)


async def test_existing_file_uses_server_object_and_requires_download_permission():
    file = SimpleNamespace(
        id=19, tenant_id=2, knowledge_id=3, file_type=1, object_name="original/19.pdf", file_name="document.pdf"
    )
    item = KnowledgeFileOne(file_path="knowledge-preview-file:19:original", preview_file_id=19)
    minio = SimpleNamespace(bucket="public", get_share_link=AsyncMock(return_value="signed"))
    with (
        patch(f"{MODULE}.get_current_tenant_id", return_value=2),
        patch(f"{MODULE}.get_minio_storage", AsyncMock(return_value=minio)),
        patch(f"{MODULE}.KnowledgeFileDao.query_by_id", AsyncMock(return_value=file)),
        patch(
            "bisheng.permission.application.business_authorization.require_business_action", AsyncMock()
        ) as permission,
    ):
        source = await PreviewSourceService.resolve(item=item, login_user=SimpleNamespace(user_id=7), knowledge_id=3)
        assert (source.bucket, source.object_name, source.cache_path) == (
            "public",
            "original/19.pdf",
            "knowledge-preview-file:19:original",
        )
        assert permission.await_args.kwargs["action"] == "download"
        file.knowledge_id = 4
        with pytest.raises(HTTPException):
            await PreviewSourceService.resolve(item=item, login_user=SimpleNamespace(user_id=7), knowledge_id=3)

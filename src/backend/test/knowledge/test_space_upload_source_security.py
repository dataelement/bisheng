from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from bisheng.knowledge.api.endpoints.knowledge_space import add_file, upload_folder
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileCreateReq, FolderUploadReq
from bisheng.knowledge.domain.services.preview_source_service import PreviewSource


async def test_folder_grant_allows_valid_upload_with_server_source():
    req = FileCreateReq(file_path=["issued"], preview_upload_refs=["token"], parent_id=12)
    source = PreviewSource("tmp", "object.pdf", "a.pdf", "issued", "issued")
    svc = SimpleNamespace(
        add_file=AsyncMock(return_value=[]), _require_action=AsyncMock(), login_user=SimpleNamespace(user_id=7)
    )
    with patch(
        "bisheng.knowledge.api.endpoints.knowledge_space.PreviewSourceService.resolve", AsyncMock(return_value=source)
    ):
        await add_file(space_id=3, req=req, svc=svc)
    svc._require_action.assert_awaited_once_with("folder", 12, "upload_file")
    assert svc.add_file.await_args.kwargs["trusted_sources"] == [source]


async def test_public_file_registration_rejects_unissued_url_before_processing():
    req = FileCreateReq(file_path=["http://127.0.0.1/admin"], preview_upload_refs=["forged"])
    svc = SimpleNamespace(add_file=AsyncMock(), _require_action=AsyncMock(), login_user=SimpleNamespace(user_id=7))
    with (
        patch("bisheng.knowledge.domain.services.preview_source_service.get_current_tenant_id", return_value=2),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.get_redis_client",
            AsyncMock(return_value=SimpleNamespace(aget=AsyncMock(return_value=None))),
        ),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.get_minio_storage",
            AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp")),
        ),
    ):
        with pytest.raises(HTTPException):
            await add_file(space_id=3, req=req, svc=svc)
    svc.add_file.assert_not_awaited()


async def test_folder_registration_rejects_unissued_url_before_creating_folders():
    req = FolderUploadReq(
        items=[{"file_path": "http://127.0.0.1/admin", "relative_path": "x/a.pdf", "preview_upload_ref": "forged"}]
    )
    svc = SimpleNamespace(
        upload_folder_items=AsyncMock(), _require_action=AsyncMock(), login_user=SimpleNamespace(user_id=7)
    )
    with (
        patch("bisheng.knowledge.domain.services.preview_source_service.get_current_tenant_id", return_value=2),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.get_redis_client",
            AsyncMock(return_value=SimpleNamespace(aget=AsyncMock(return_value=None))),
        ),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.get_minio_storage",
            AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp")),
        ),
    ):
        with pytest.raises(HTTPException):
            await upload_folder(space_id=3, req=req, svc=svc)
    svc.upload_folder_items.assert_not_awaited()

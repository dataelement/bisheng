from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, UploadFile

from bisheng.api.v1.schemas import KnowledgeFileOne
from bisheng.knowledge.api.endpoints.knowledge import upload_knowledge_file
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.preview_source_service import PreviewSource


async def test_space_upload_staging_does_not_require_library_edit():
    knowledge = SimpleNamespace(id=4, user_id=1, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value)
    file = UploadFile(filename="a.pdf", file=BytesIO(b"file"))
    user = SimpleNamespace(user_id=8, tenant_id=1)
    with (
        patch("bisheng.knowledge.api.endpoints.knowledge.get_current_tenant_id", return_value=1),
        patch("bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.aquery_by_id", AsyncMock(return_value=knowledge)),
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.permission_service.ensure_knowledge_write_async",
            AsyncMock(side_effect=AssertionError("not a library")),
        ) as library_edit,
        patch("bisheng.knowledge.api.endpoints.knowledge.generate_uuid", return_value="random"),
        patch("bisheng.knowledge.domain.upload_file_size.settings", SimpleNamespace(get_from_db=lambda key: {})),
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.save_uploaded_file",
            AsyncMock(return_value="https://minio/tmp/random.pdf"),
        ),
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.KnowledgeFileDao.get_repeat_file", AsyncMock(return_value=None)
        ),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.PreviewSourceService.issue",
            AsyncMock(return_value="issued"),
        ),
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.get_minio_storage",
            AsyncMock(return_value=SimpleNamespace(tmp_bucket="tmp")),
        ),
        patch(
            "bisheng.knowledge.domain.services.preview_source_service.PreviewSourceService.bind_owned_object",
            AsyncMock(),
        ),
    ):
        response = await upload_knowledge_file.__wrapped__(request=None, login_user=user, knowledge_id=4, file=file)
        assert response.data.file_path == "https://minio/tmp/random.pdf"
        assert response.data.preview_upload_ref == "issued"
        library_edit.assert_not_awaited()


async def test_missing_knowledge_returns_not_found():
    file = UploadFile(filename="a.pdf", file=BytesIO(b"file"))
    with patch("bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.aquery_by_id", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await upload_knowledge_file.__wrapped__(
                request=None, login_user=SimpleNamespace(user_id=8), knowledge_id=4, file=file
            )
        assert exc.value.status_code == 404


def test_space_upload_prepares_original_name_from_resolved_source(tmp_path, monkeypatch):
    object_name = "uploads/1/8/49a1ae00092a42b286de22fe93d85064.md"
    source = PreviewSource("tmp", object_name, "会议纪要.md", "issued", "issued")
    local_file = tmp_path / "content_hash.md"
    local_file.write_text("# 会议纪要", encoding="utf-8")
    storage = Mock()
    monkeypatch.setattr("bisheng.knowledge.domain.services.knowledge_service.get_minio_storage_sync", lambda: storage)
    monkeypatch.setattr("bisheng.core.cache.utils.save_download_file", lambda *_: str(local_file))
    monkeypatch.setattr(KnowledgeService, "get_upload_file_original_name", lambda file_name: file_name)

    prepared = KnowledgeService.prepare_one_file(
        SimpleNamespace(user_id=8),
        SimpleNamespace(id=4),
        KnowledgeFileOne(file_path=source.cache_path),
        {},
        trusted_source=source,
    )

    storage.download_object_sync.assert_called_once_with("tmp", object_name)
    assert prepared.original_file_name == source.file_name

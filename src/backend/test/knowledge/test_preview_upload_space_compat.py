from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from bisheng.knowledge.api.endpoints.knowledge import upload_knowledge_file
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum


async def test_space_upload_staging_does_not_require_library_edit():
    knowledge = SimpleNamespace(id=4, user_id=1, type=KnowledgeTypeEnum.SPACE.value)
    file = UploadFile(filename="a.pdf", file=BytesIO(b"file"))
    user = SimpleNamespace(user_id=8)
    with (
        patch("bisheng.knowledge.api.endpoints.knowledge.KnowledgeDao.aquery_by_id", AsyncMock(return_value=knowledge)),
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.permission_service.ensure_knowledge_write_async",
            AsyncMock(side_effect=AssertionError("not a library")),
        ) as library_edit,
        patch(
            "bisheng.knowledge.api.endpoints.knowledge.KnowledgeService.save_upload_file_original_name",
            AsyncMock(return_value="random.pdf"),
        ),
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

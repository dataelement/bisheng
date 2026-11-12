from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.v1.schemas import KnowledgeFileOne
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService

MODULE = "bisheng.knowledge.domain.services.preview_source_service"


@pytest.mark.parametrize("legacy", [False, True])
async def test_existing_converted_source_is_server_selected(legacy):
    file = SimpleNamespace(
        id=19,
        tenant_id=2,
        knowledge_id=3,
        file_type=1,
        object_name="original/19.doc",
        file_name="a.doc",
        preview_file_object_name=None if legacy else "preview/19.docx",
        parse_type="local",
    )
    minio = SimpleNamespace(
        bucket="public", get_share_link=AsyncMock(return_value="signed"), object_exists=AsyncMock(return_value=True)
    )
    item = KnowledgeFileOne(
        file_path="knowledge-preview-file:19:converted", preview_file_id=19, preview_source="converted"
    )
    with (
        patch(f"{MODULE}.get_current_tenant_id", return_value=2),
        patch(f"{MODULE}.get_minio_storage", AsyncMock(return_value=minio)),
        patch(f"{MODULE}.KnowledgeFileDao.query_by_id", AsyncMock(return_value=file)),
        patch("bisheng.permission.application.business_authorization.require_business_action", AsyncMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_utils.KnowledgeUtils.resolve_preview_object_name",
            return_value="preview/19.docx",
        ),
    ):
        source = await PreviewSourceService.resolve(item=item, login_user=SimpleNamespace(user_id=7), knowledge_id=3)
        assert source.object_name == ("19" if legacy else "preview/19.docx")

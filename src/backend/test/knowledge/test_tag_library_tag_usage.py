from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


@pytest.mark.asyncio
async def test_count_total_usage_uses_json_fallback_when_tag_rows_missing():
    manual = ["安全生产", "制度"]
    with (
        patch.object(
            TagLibraryTagService,
            "list_tags",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            TagLibraryTagService,
            "count_usage_batch",
            new=AsyncMock(
                return_value={
                    ("安全生产", TagResourceTypeEnum.MANUAL_TAG.value): 3,
                    ("制度", TagResourceTypeEnum.MANUAL_TAG.value): 2,
                }
            ),
        ) as count_usage_batch,
    ):
        total = await TagLibraryTagService.count_total_usage(
            library_id=1,
            tenant_id=1,
            manual_tags=manual,
            ai_tags=[],
        )

    assert total == 5
    count_usage_batch.assert_awaited_once()
    items = count_usage_batch.await_args.kwargs["items"]
    assert ("安全生产", TagResourceTypeEnum.MANUAL_TAG.value) in items
    assert ("制度", TagResourceTypeEnum.MANUAL_TAG.value) in items


@pytest.mark.asyncio
async def test_resolve_file_tag_ids_excludes_tag_library_rows():
    with patch("bisheng.knowledge.domain.services.tag_library_tag_service.get_async_db_session") as session_ctx:
        session = AsyncMock()
        session_ctx.return_value.__aenter__.return_value = session
        session.exec = AsyncMock(return_value=AsyncMock(all=lambda: [101, 102]))

        tag_ids = await TagLibraryTagService._resolve_file_tag_ids(
            items=[("安全生产", TagResourceTypeEnum.MANUAL_TAG.value)],
            tenant_id=1,
        )

    assert tag_ids == [101, 102]
    compiled = str(session.exec.await_args.args[0])
    assert "tag.business_type !=" in compiled

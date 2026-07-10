from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_public_space_list_skips_user_specific_enrichment():
    space = Knowledge(
        id=10,
        name="Public space",
        user_id=22,
        type=KnowledgeTypeEnum.SPACE.value,
    )
    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
            new=AsyncMock(return_value=[10]),
        ) as scope_ids,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_spaces_by_ids",
            new=AsyncMock(return_value=[space]),
        ) as spaces_by_ids,
    ):
        result = await service.get_public_spaces("update_time")

    scope_ids.assert_awaited_once_with(KnowledgeSpaceLevelEnum.PUBLIC)
    spaces_by_ids.assert_awaited_once_with([10], "update_time")
    assert result == [{**space.model_dump(), "space_level": "public"}]
    assert "file_num" not in result[0]
    assert "department_name" not in result[0]

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=1, tenant_id=1, user_name="tester")


def _library(**overrides) -> KnowledgeSpaceTagLibrary:
    data = {
        "id": 2,
        "tenant_id": 1,
        "name": "测试2",
        "description": "",
        "tags": [],
        "ai_tags": [],
        "tag_count": 0,
        "is_builtin": False,
        "owner_knowledge_id": None,
        "user_id": 1,
    }
    data.update(overrides)
    return KnowledgeSpaceTagLibrary(**data)


@pytest.mark.asyncio
async def test_update_library_rejects_tag_existing_in_other_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=([], [], [])),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service."
            "TagLibraryTagService.find_names_used_in_other_libraries",
            new=AsyncMock(return_value=["安全生产"]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.replace_tags",
            new=AsyncMock(),
        ) as replace_tags,
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="其他标签库"):
            await service.update_library(2, tags=["安全生产"])

    replace_tags.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_library_rejects_tag_existing_in_other_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())

    with (
        patch.object(
            KnowledgeSpaceTagLibraryService,
            "_ensure_public_name_available",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service."
            "TagLibraryTagService.find_names_used_in_other_libraries",
            new=AsyncMock(return_value=["制度"]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.ainsert",
            new=AsyncMock(),
        ) as insert_mock,
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="其他标签库"):
            await service.create_library("新库", "说明", ["制度"])

    insert_mock.assert_not_awaited()

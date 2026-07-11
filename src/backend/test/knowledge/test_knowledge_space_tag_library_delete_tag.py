from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=1, tenant_id=1, user_name="tester")


def _library(**overrides) -> KnowledgeSpaceTagLibrary:
    data = {
        "id": 1,
        "tenant_id": 1,
        "name": "业务标签库",
        "description": "",
        "tags": ["合同", "制度"],
        "ai_tags": ["AI标签"],
        "tag_count": 3,
        "is_builtin": False,
        "owner_knowledge_id": None,
        "user_id": 1,
    }
    data.update(overrides)
    return KnowledgeSpaceTagLibrary(**data)


@pytest.mark.asyncio
async def test_delete_library_tag_removes_system_tag_without_global_unique_check():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同", "制度"], [], ["AI标签"])),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service."
            "TagLibraryTagService.find_names_used_in_other_libraries",
            new=AsyncMock(),
        ) as find_duplicates,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.replace_tags",
            new=AsyncMock(),
        ) as replace_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(return_value=library),
        ) as update_library,
        patch.object(service, "to_detail", new=AsyncMock(return_value=SimpleNamespace(id=1))),
    ):
        await service.delete_library_tag(1, "合同", TagResourceTypeEnum.SYSTEM_TAG.value)

    find_duplicates.assert_not_awaited()
    replace_tags.assert_awaited_once_with(
        library_id=1,
        tenant_id=1,
        user_id=1,
        system_tags=["制度"],
        manual_tags=[],
        ai_tags=["AI标签"],
    )
    update_library.assert_awaited_once_with(1, tags=["制度"], ai_tags=["AI标签"], tag_count=2)


@pytest.mark.asyncio
async def test_delete_library_tag_raises_when_tag_missing():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同"], [], [])),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="标签不存在"):
            await service.delete_library_tag(1, "制度", TagResourceTypeEnum.SYSTEM_TAG.value)

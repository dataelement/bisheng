from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    DEFAULT_TAG_LIBRARY_NAME,
    MAX_LIBRARY_NAME_LENGTH,
    KnowledgeSpaceTagLibraryService,
)


def test_normalize_name_rejects_empty():
    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="不能为空"):
        KnowledgeSpaceTagLibraryService.normalize_name("   ")


def test_normalize_name_rejects_too_long():
    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="不能超过"):
        KnowledgeSpaceTagLibraryService.normalize_name("a" * (MAX_LIBRARY_NAME_LENGTH + 1))


def test_normalize_name_allows_special_symbols():
    assert KnowledgeSpaceTagLibraryService.normalize_name(" 测试@#-库_1 ") == "测试@#-库_1"


@pytest.mark.asyncio
async def test_create_library_rejects_duplicate_name():
    service = KnowledgeSpaceTagLibraryService(type("User", (), {"user_id": 1, "tenant_id": 1})())
    with (
        patch.object(
            KnowledgeSpaceTagLibraryService,
            "_ensure_public_name_available",
            new=AsyncMock(side_effect=KnowledgeSpaceTagLibraryInvalidError(msg="标签库名称已存在")),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.ainsert",
            new=AsyncMock(),
        ) as insert,
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="标签库名称已存在"):
            await service.create_library("重复库", None, [])
        insert.assert_not_awaited()


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=1, tenant_id=1)


@pytest.mark.asyncio
async def test_update_library_rejects_renaming_default_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = SimpleNamespace(
        id=1,
        name=DEFAULT_TAG_LIBRARY_NAME,
        owner_knowledge_id=None,
        tags=[],
        ai_tags=[],
        tenant_id=1,
        user_id=1,
    )
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(),
        ) as update,
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="不可修改名称"):
            await service.update_library(1, name="自定义库")
        update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_library_allows_keeping_default_library_name():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = SimpleNamespace(
        id=1,
        name=DEFAULT_TAG_LIBRARY_NAME,
        owner_knowledge_id=None,
        tags=[],
        ai_tags=[],
        tenant_id=1,
        user_id=1,
    )
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
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(return_value=library),
        ) as update,
        patch.object(service, "to_detail", new=AsyncMock(return_value={"id": 1})),
    ):
        await service.update_library(1, name=DEFAULT_TAG_LIBRARY_NAME, description="说明")
    update.assert_awaited_once()

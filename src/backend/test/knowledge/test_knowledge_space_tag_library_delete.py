from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=1, tenant_id=1)


def _library(**overrides) -> SimpleNamespace:
    base = {
        "id": 1,
        "tenant_id": 1,
        "user_id": 1,
        "name": "测试库",
        "description": None,
        "tags": [],
        "ai_tags": [],
        "tag_count": 0,
        "is_builtin": False,
        "owner_knowledge_id": None,
        "create_time": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_delete_library_rejects_when_library_has_tags():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library(tags=["安全生产"])

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch.object(
            service,
            "_resolve_library_tags",
            new=AsyncMock(return_value=(["安全生产"], 1)),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="标签库中存在标签"):
            await service.delete_library(1)


@pytest.mark.asyncio
async def test_delete_library_rejects_when_bound_to_knowledge_spaces():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch.object(
            service,
            "_resolve_library_tags",
            new=AsyncMock(return_value=([], 0)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeTagLibraryLinkDao.acount_bound_knowledge_spaces",
            new=AsyncMock(return_value=2),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="标签库已关联知识空间"):
            await service.delete_library(1)


@pytest.mark.asyncio
async def test_delete_library_succeeds_for_empty_unbound_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch.object(
            service,
            "_resolve_library_tags",
            new=AsyncMock(return_value=([], 0)),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeTagLibraryLinkDao.acount_bound_knowledge_spaces",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.delete_for_library",
            new=AsyncMock(),
        ) as delete_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.adelete",
            new=AsyncMock(),
        ) as delete_library,
    ):
        await service.delete_library(1)

    delete_tags.assert_awaited_once_with(1)
    delete_library.assert_awaited_once_with(1)

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def _public_library(library_id: int, *, tags: list[str] | None = None) -> KnowledgeSpaceTagLibrary:
    return KnowledgeSpaceTagLibrary(
        id=library_id,
        tenant_id=1,
        name=f"library-{library_id}",
        tags=tags or [],
        tag_count=len(tags or []),
    )


@pytest.mark.asyncio
async def test_validate_bindable_libraries_rejects_when_all_libraries_empty():
    empty_a = _public_library(1)
    empty_b = _public_library(2)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(side_effect=[empty_a, empty_b]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=([], [], [])),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="非空标签库"):
            await KnowledgeSpaceTagLibraryService.validate_bindable_libraries([1, 2])


@pytest.mark.asyncio
async def test_validate_bindable_libraries_passes_when_any_library_has_tags():
    empty_library = _public_library(1)
    tagged_library = _public_library(2, tags=["政策"])

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(side_effect=[empty_library, tagged_library]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(side_effect=[([], [], []), (["政策"], [], [])]),
        ),
    ):
        await KnowledgeSpaceTagLibraryService.validate_bindable_libraries([1, 2])

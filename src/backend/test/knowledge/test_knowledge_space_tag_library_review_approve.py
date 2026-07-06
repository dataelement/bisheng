from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import (
    KnowledgeSpaceTagLibraryListItem,
)
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=1, tenant_id=1)


def _library(**overrides) -> SimpleNamespace:
    base = {
        "id": 10,
        "tenant_id": 1,
        "user_id": 1,
        "name": "业务标签库",
        "description": None,
        "tags": ["合同"],
        "ai_tags": [],
        "tag_count": 1,
        "is_builtin": False,
        "owner_knowledge_id": None,
        "create_time": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_validate_library_bound_to_knowledge_rejects_unbound_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())

    with patch.object(
        KnowledgeSpaceTagLibraryService,
        "resolve_bound_library_ids",
        new=AsyncMock(return_value=[20, 30]),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="未关联此知识空间"):
            await service.validate_library_bound_to_knowledge(library_id=10, knowledge_id=100)


@pytest.mark.asyncio
async def test_list_bound_libraries_for_knowledge_skips_private_libraries():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    public_library = _library(id=10, owner_knowledge_id=None)
    private_library = _library(id=11, owner_knowledge_id=99, name="私有库")

    list_item = KnowledgeSpaceTagLibraryListItem(
        id=10,
        name="业务标签库",
        description=None,
        tag_count=1,
        bound_space_count=1,
        bound_space_names=["测试空间"],
        used_knowledge_count=0,
        is_builtin=False,
    )

    to_list_item_mock = AsyncMock(return_value=list_item)

    with (
        patch.object(
            KnowledgeSpaceTagLibraryService,
            "resolve_bound_library_ids",
            new=AsyncMock(return_value=[10, 11]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(side_effect=[public_library, private_library]),
        ),
        patch.object(service, "to_list_item", new=to_list_item_mock),
    ):
        items = await service.list_bound_libraries_for_knowledge(100)

    assert len(items) == 1
    assert items[0].id == 10
    to_list_item_mock.assert_awaited_once_with(public_library)


@pytest.mark.asyncio
async def test_append_review_tag_adds_ai_tag_to_bound_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library(tags=["合同"], ai_tags=[])

    with (
        patch.object(service, "validate_library_bound_to_knowledge", new=AsyncMock()),
        patch.object(service, "_ensure_global_tag_names_available", new=AsyncMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同"], [], [])),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.replace_tags",
            new=AsyncMock(),
        ) as replace_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(),
        ) as update_library,
    ):
        await service.append_review_tag(
            library_id=10,
            knowledge_id=100,
            tag_name="AI助手功能",
            review_resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
        )

    replace_tags.assert_awaited_once_with(
        library_id=10,
        tenant_id=1,
        user_id=1,
        system_tags=["合同"],
        manual_tags=[],
        ai_tags=["AI助手功能"],
    )
    update_library.assert_awaited_once_with(
        10,
        tags=["合同"],
        ai_tags=["AI助手功能"],
        tag_count=2,
    )


@pytest.mark.asyncio
async def test_append_review_tag_adds_manual_tag_to_bound_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library(tags=["合同"], ai_tags=[])

    with (
        patch.object(service, "validate_library_bound_to_knowledge", new=AsyncMock()),
        patch.object(service, "_ensure_global_tag_names_available", new=AsyncMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同"], [], [])),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.replace_tags",
            new=AsyncMock(),
        ) as replace_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(),
        ) as update_library,
    ):
        await service.append_review_tag(
            library_id=10,
            knowledge_id=100,
            tag_name="人工新标签",
            review_resource_type=TagResourceTypeEnum.MANUAL_TAG.value,
        )

    replace_tags.assert_awaited_once_with(
        library_id=10,
        tenant_id=1,
        user_id=1,
        system_tags=["合同"],
        manual_tags=["人工新标签"],
        ai_tags=[],
    )
    update_library.assert_awaited_once_with(
        10,
        tags=["合同", "人工新标签"],
        ai_tags=[],
        tag_count=2,
    )


@pytest.mark.asyncio
async def test_append_review_tag_skips_manual_when_name_already_in_system():
    service = KnowledgeSpaceTagLibraryService(_login_user())
    library = _library(tags=["合同", "安全生产"], ai_tags=[])

    with (
        patch.object(service, "validate_library_bound_to_knowledge", new=AsyncMock()),
        patch.object(service, "_ensure_global_tag_names_available", new=AsyncMock()) as ensure_available,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同", "安全生产"], [], [])),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.TagLibraryTagService.replace_tags",
            new=AsyncMock(),
        ) as replace_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryDao.aupdate",
            new=AsyncMock(),
        ) as update_library,
    ):
        await service.append_review_tag(
            library_id=10,
            knowledge_id=100,
            tag_name="安全生产",
            review_resource_type=TagResourceTypeEnum.MANUAL_TAG.value,
        )

    ensure_available.assert_not_awaited()
    replace_tags.assert_awaited_once_with(
        library_id=10,
        tenant_id=1,
        user_id=1,
        system_tags=["合同", "安全生产"],
        manual_tags=[],
        ai_tags=[],
    )
    update_library.assert_awaited_once_with(
        10,
        tags=["合同", "安全生产"],
        ai_tags=[],
        tag_count=2,
    )


@pytest.mark.asyncio
async def test_append_review_tag_rejects_unbound_library():
    service = KnowledgeSpaceTagLibraryService(_login_user())

    with patch.object(
        service,
        "validate_library_bound_to_knowledge",
        new=AsyncMock(
            side_effect=KnowledgeSpaceTagLibraryInvalidError(msg="该标签库未关联此知识空间"),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="未关联此知识空间"):
            await service.append_review_tag(
                library_id=10,
                knowledge_id=100,
                tag_name="新标签",
                review_resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
            )

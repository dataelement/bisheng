"""Tests for knowledge space tag create/list idempotency."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import ReviewTagFeatureDisabledError
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.fixture
def service():
    login_user = SimpleNamespace(user_id=1, tenant_id=1, user_name="tester")
    return KnowledgeSpaceService(MagicMock(), login_user)


@pytest.mark.asyncio
async def test_add_space_tag_returns_existing_approved_tag(service):
    existing = SimpleNamespace(id=10, name="已有标签")

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
        ) as mock_insert,
    ):
        result = await service.add_space_tag(137, "已有标签")

    assert result is existing
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_space_tag_returns_existing_review_tag(service):
    existing = SimpleNamespace(id=20, name="待审核", review_status=0)

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[existing],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
        ) as mock_insert,
    ):
        result = await service.add_space_tag(137, "待审核")

    assert result is existing
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_space_tags_includes_pending_review_tags(service):
    approved = SimpleNamespace(id=1, name="已生效")
    pending = SimpleNamespace(id=2, name="待审核", review_status=0)

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[approved],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[pending],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [approved, pending]


@pytest.mark.asyncio
async def test_get_space_tags_includes_bound_library_tags(service):
    approved = SimpleNamespace(id=1, name="已生效")
    library_tag = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[approved],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[2],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService.list_tags",
            new_callable=AsyncMock,
            return_value=[library_tag],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [approved, library_tag]


@pytest.mark.asyncio
async def test_add_space_tag_returns_bound_library_tag(service):
    library_tag = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            service,
            "_find_bound_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=library_tag,
        ),
        patch.object(
            KnowledgeSpaceService,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
        ) as mock_insert,
    ):
        result = await service.add_space_tag(137, "安全生产")

    assert result is library_tag
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_space_tag_rejects_library_tag_when_review_feature_disabled(service):
    library_tag = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            service,
            "_find_bound_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=library_tag,
        ),
        patch.object(
            KnowledgeSpaceService,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
            side_effect=ReviewTagFeatureDisabledError(),
        ),
    ):
        with pytest.raises(ReviewTagFeatureDisabledError):
            await service.add_space_tag(137, "安全生产")


@pytest.mark.asyncio
async def test_add_space_tag_rejects_when_review_feature_disabled(service):
    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            service,
            "_find_bound_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            KnowledgeSpaceService,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
            side_effect=ReviewTagFeatureDisabledError(),
        ),
    ):
        with pytest.raises(ReviewTagFeatureDisabledError):
            await service.add_space_tag(137, "新标签")


@pytest.mark.asyncio
async def test_update_file_tags_rejects_review_tags_when_feature_disabled(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137)

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch.object(
            KnowledgeSpaceService,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
            side_effect=ReviewTagFeatureDisabledError(),
        ),
    ):
        with pytest.raises(ReviewTagFeatureDisabledError):
            await service.update_file_tags(137, 10, [1], [2])

    mock_update_tags.assert_awaited_once()

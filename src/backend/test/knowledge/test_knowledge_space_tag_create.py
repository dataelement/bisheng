"""Tests for knowledge space tag create/list idempotency."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import KnowledgeSpaceTagLibraryNotBoundError, ReviewTagFeatureDisabledError
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.fixture
def service():
    login_user = SimpleNamespace(user_id=1, tenant_id=1, user_name="tester")
    svc = KnowledgeSpaceService(MagicMock(), login_user)
    svc._find_tenant_pending_review_tag_by_name = AsyncMock(return_value=None)
    return svc


@pytest.mark.asyncio
async def test_add_space_tag_returns_existing_approved_tag(service):
    existing = SimpleNamespace(id=10, name="已有标签")

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=existing),
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
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=existing),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
        ) as mock_insert,
    ):
        result = await service.add_space_tag(137, "待审核")

    assert result is existing
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_space_tag_returns_existing_review_tag_without_create(service):
    existing = SimpleNamespace(
        id=20,
        name="待审核",
        review_status=0,
        business_type="tag_library",
        business_id="5",
        resource_type="manual_tag",
    )
    library = SimpleNamespace(id=5, name="测试库")

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(
            service,
            "_find_space_tag_by_name",
            new_callable=AsyncMock,
            return_value=existing,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new_callable=AsyncMock,
            return_value=[2, 3],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aget",
            new_callable=AsyncMock,
            return_value=library,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
        ) as mock_insert,
    ):
        result = await service.lookup_space_tag(137, "待审核")

    assert result == {
        "id": 20,
        "name": "待审核",
        "resource_type": "manual_tag",
        "business_type": "tag_library",
        "review_status": 0,
        "tag_library_id": 5,
        "tag_library_name": "测试库",
        "is_bound_to_space": False,
    }
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_space_tag_returns_unbound_library_tag(service):
    existing = SimpleNamespace(
        id=30,
        name="外部标签",
        business_type="tag_library",
        business_id="99",
        resource_type="system_tag",
    )
    library = SimpleNamespace(id=99, name="外部库")

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(
            service,
            "_find_space_tag_by_name",
            new_callable=AsyncMock,
            return_value=existing,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new_callable=AsyncMock,
            return_value=[2, 3],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aget",
            new_callable=AsyncMock,
            return_value=library,
        ),
    ):
        result = await service.lookup_space_tag(137, "外部标签")

    assert result == {
        "id": 30,
        "name": "外部标签",
        "resource_type": "system_tag",
        "business_type": "tag_library",
        "review_status": 1,
        "tag_library_id": 99,
        "tag_library_name": "外部库",
        "is_bound_to_space": False,
    }


@pytest.mark.asyncio
async def test_lookup_space_tag_returns_none_when_not_found(service):
    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=None),
    ):
        result = await service.lookup_space_tag(137, "全新标签")

    assert result is None


@pytest.mark.asyncio
async def test_find_space_tag_by_name_falls_back_to_tenant_pending_review_tag(service):
    pending = SimpleNamespace(
        id=31,
        name="11",
        review_status=0,
        business_type="knowledge_space",
        business_id="121",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_find_bound_library_tag_by_name", new_callable=AsyncMock, return_value=None),
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
            "_find_pending_review_tag_in_bound_libraries",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            service,
            "_find_tenant_pending_review_tag_by_name",
            new_callable=AsyncMock,
            return_value=pending,
        ) as mock_tenant_pending,
        patch.object(
            service,
            "_find_tenant_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_library,
    ):
        result = await service._find_space_tag_by_name(121, "11")

    assert result is pending
    mock_tenant_pending.assert_awaited_once_with("11", space_id=121)
    mock_library.assert_awaited_once_with("11")


@pytest.mark.asyncio
async def test_get_space_tags_returns_only_bound_library_tags(service):
    library_tag_a = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="system_tag",
    )
    library_tag_b = SimpleNamespace(
        id=101,
        name="制度",
        business_type="tag_library",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[2, 3],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids",
            new_callable=AsyncMock,
            return_value={"2": [library_tag_a], "3": [library_tag_b]},
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService._repair_legacy_library_resource_types",
            new_callable=AsyncMock,
            side_effect=lambda tags: tags,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [library_tag_a, library_tag_b]


@pytest.mark.asyncio
async def test_get_space_tags_dedupes_tags_across_libraries(service):
    library_tag = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="system_tag",
    )

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[2, 3],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids",
            new_callable=AsyncMock,
            return_value={"2": [library_tag], "3": [library_tag]},
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService._repair_legacy_library_resource_types",
            new_callable=AsyncMock,
            side_effect=lambda tags: tags,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [library_tag]


@pytest.mark.asyncio
async def test_get_space_tags_dedupes_same_name_across_resource_types(service):
    system_tag = SimpleNamespace(
        id=100,
        name="安全生产",
        business_type="tag_library",
        resource_type="system_tag",
    )
    manual_tag = SimpleNamespace(
        id=101,
        name="安全生产",
        business_type="tag_library",
        resource_type="manual_tag",
    )

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[2],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids",
            new_callable=AsyncMock,
            return_value={"2": [system_tag, manual_tag]},
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService._repair_legacy_library_resource_types",
            new_callable=AsyncMock,
            side_effect=lambda tags: tags,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [system_tag]


@pytest.mark.asyncio
async def test_get_space_tags_includes_pending_review_tags(service):
    pending_tag = SimpleNamespace(
        id=200,
        name="待审核人工",
        business_type="tag_library",
        business_id="2",
        resource_type="manual_tag",
        review_status=0,
        is_deleted=False,
    )

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[2],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            side_effect=lambda business_type, business_id, name=None: (
                [pending_tag] if business_type == TagBusinessTypeEnum.TAG_LIBRARY and business_id == "2" else []
            ),
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == [pending_tag]


@pytest.mark.asyncio
async def test_get_space_tags_returns_empty_when_no_bound_libraries(service):
    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_tags_by_business_ids",
            new_callable=AsyncMock,
        ) as mock_get_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.get_tags_by_business",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.get_space_tags(137)

    assert result == []
    mock_get_tags.assert_not_awaited()


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
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=library_tag),
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
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=library_tag),
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
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=None),
        patch.object(
            service,
            "_resolve_primary_library_for_space",
            new_callable=AsyncMock,
            return_value=5,
        ),
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
            side_effect=ReviewTagFeatureDisabledError(),
        ),
    ):
        with pytest.raises(ReviewTagFeatureDisabledError):
            await service.add_space_tag(137, "新标签")


@pytest.mark.asyncio
async def test_add_space_tag_creates_review_tag_with_tenant_id(service):
    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=None),
        patch.object(
            service,
            "_resolve_primary_library_for_space",
            new_callable=AsyncMock,
            return_value=5,
        ),
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.ainsert_review_tag",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=99, name="新标签", review_status=0),
        ) as mock_insert,
    ):
        await service.add_space_tag(137, "新标签")

    inserted = mock_insert.await_args.args[0]
    assert inserted.tenant_id == 1
    assert inserted.review_status == 0
    assert inserted.business_type == TagBusinessTypeEnum.TAG_LIBRARY
    assert inserted.business_id == "5"
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        ) as mock_session_ctx,
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
        patch.object(
            service,
            "_promote_review_tags_existing_in_libraries",
            new_callable=AsyncMock,
            side_effect=lambda tag_ids, review_tag_ids: (tag_ids, review_tag_ids),
        ),
    ):
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [1]),
                SimpleNamespace(all=lambda: [20]),
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.update_file_tags(137, 10, [1, 20], [])

    mock_update_tags.assert_awaited_once_with([1], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_update_review_tags.assert_awaited_once_with([20], "10", ResourceTypeEnum.SPACE_FILE, 1, tenant_id=1)


@pytest.mark.asyncio
async def test_partition_keeps_approved_tag_id_colliding_with_review_id(service):
    """A real Tag id must stay in tag_ids even if a ReviewTag shares the same id."""
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
    ) as mock_session_ctx:
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [5]),  # Tag.id in (5) -> 5 is a real Tag
                SimpleNamespace(all=lambda: [5]),  # ReviewTag.id in (5) -> collision
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        tags, review = await service._partition_file_tag_ids_for_update([5], [])

    assert tags == [5]
    assert review == []


@pytest.mark.asyncio
async def test_partition_reroutes_review_id_only_when_not_a_tag(service):
    """A pending id sent in tag_ids moves to review only when it is not a Tag."""
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
    ) as mock_session_ctx:
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: []),  # Tag.id in (7) -> not a Tag
                SimpleNamespace(all=lambda: [7]),  # ReviewTag.id in (7) -> genuine review tag
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        tags, review = await service._partition_file_tag_ids_for_update([7], [])

    assert tags == []
    assert review == [7]


@pytest.mark.asyncio
async def test_update_file_tags_saves_both_approved_and_pending_tags(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        ) as mock_session_ctx,
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
        patch.object(
            service,
            "_promote_review_tags_existing_in_libraries",
            new_callable=AsyncMock,
            side_effect=lambda tag_ids, review_tag_ids: (tag_ids, review_tag_ids),
        ),
    ):
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [12]),
                SimpleNamespace(all=lambda: [2]),
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.update_file_tags(137, 10, [12], [2])

    mock_update_tags.assert_awaited_once_with([12], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_update_review_tags.assert_awaited_once_with([2], "10", ResourceTypeEnum.SPACE_FILE, 1, tenant_id=1)


@pytest.mark.asyncio
async def test_update_file_tags_moves_misclassified_tag_ids_out_of_review_tag_ids(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        ) as mock_session_ctx,
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
        patch.object(
            service,
            "_promote_review_tags_existing_in_libraries",
            new_callable=AsyncMock,
            side_effect=lambda tag_ids, review_tag_ids: (tag_ids, review_tag_ids),
        ),
    ):
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [12]),
                SimpleNamespace(all=lambda: []),
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.update_file_tags(137, 10, [], [12])

    mock_update_tags.assert_awaited_once_with([12], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_update_review_tags.assert_awaited_once_with([], "10", ResourceTypeEnum.SPACE_FILE, 1, tenant_id=1)


@pytest.mark.asyncio
async def test_add_space_tag_rejects_when_space_has_no_bound_library(service):
    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=None),
        patch.object(
            service,
            "_resolve_primary_library_for_space",
            new_callable=AsyncMock,
            side_effect=KnowledgeSpaceTagLibraryNotBoundError(),
        ),
    ):
        with pytest.raises(KnowledgeSpaceTagLibraryNotBoundError):
            await service.add_space_tag(137, "新标签")


@pytest.mark.asyncio
async def test_update_file_tags_rejects_review_tags_when_feature_disabled(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(
            service,
            "_partition_file_tag_ids_for_update",
            new_callable=AsyncMock,
            return_value=([1], [2]),
        ),
        patch.object(
            service,
            "_promote_review_tags_existing_in_libraries",
            new_callable=AsyncMock,
            return_value=([1], [2]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ),
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


@pytest.mark.asyncio
async def test_add_space_tag_skips_review_when_tag_exists_in_any_library(service):
    library_tag = SimpleNamespace(
        id=100,
        name="全局标签",
        business_type="tag_library",
        resource_type="system_tag",
    )

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_find_space_tag_by_name", new_callable=AsyncMock, return_value=library_tag),
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
        result = await service.add_space_tag(137, "全局标签")

    assert result is library_tag
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_file_tags_promotes_review_tag_when_name_exists_in_library(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")
    review_tag = SimpleNamespace(id=20, name="库内标签")
    library_tag = SimpleNamespace(id=100, name="库内标签")

    with (
        patch.object(service, "_get_file_for_action", new_callable=AsyncMock, return_value=file_record),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch.object(
            service,
            "_partition_file_tag_ids_for_update",
            new_callable=AsyncMock,
            return_value=([1], [20]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        ) as mock_session_ctx,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService.find_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=library_tag,
        ),
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.aupdate_resource_tags",
            new_callable=AsyncMock,
        ) as mock_update_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
    ):
        session = AsyncMock()
        session.exec = AsyncMock(return_value=SimpleNamespace(all=lambda: [review_tag]))
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.update_file_tags(137, 10, [1], [20])

    mock_update_tags.assert_awaited_once_with([1, 100], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_update_review_tags.assert_awaited_once_with([], "10", ResourceTypeEnum.SPACE_FILE, 1, tenant_id=1)


@pytest.mark.asyncio
async def test_batch_add_file_tags_promotes_review_tag_when_name_exists_in_library(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")
    review_tag = SimpleNamespace(id=20, name="库内标签")
    library_tag = SimpleNamespace(id=100, name="库内标签")

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock, return_value=[file_record]),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch.object(
            service,
            "_partition_file_tag_ids_for_update",
            new_callable=AsyncMock,
            return_value=([1], [20]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        ) as mock_session_ctx,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService.find_library_tag_by_name",
            new_callable=AsyncMock,
            return_value=library_tag,
        ),
        patch.object(
            service,
            "_require_review_tag_feature_enabled",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.add_tags",
            new_callable=AsyncMock,
        ) as mock_add_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.add_tags",
            new_callable=AsyncMock,
        ) as mock_add_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
    ):
        session = AsyncMock()
        session.exec = AsyncMock(return_value=SimpleNamespace(all=lambda: [review_tag]))
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await service.batch_add_file_tags(137, [10], [1], [20])

    mock_add_tags.assert_awaited_once_with([1, 100], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_add_review_tags.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_add_file_tags_allows_tag_ids_only(service):
    file_record = SimpleNamespace(id=10, knowledge_id=137, file_name="demo.pdf")

    with (
        patch.object(service, "_require_read_permission", new_callable=AsyncMock),
        patch.object(service, "_get_space_files_or_raise", new_callable=AsyncMock, return_value=[file_record]),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(service, "_notify_favorite_source_changed", new_callable=AsyncMock),
        patch.object(
            service,
            "_partition_file_tag_ids_for_update",
            new_callable=AsyncMock,
            return_value=([1], []),
        ),
        patch.object(
            service,
            "_promote_review_tags_existing_in_libraries",
            new_callable=AsyncMock,
            return_value=([1], []),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.add_tags",
            new_callable=AsyncMock,
        ) as mock_add_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.ReviewTagDao.add_tags",
            new_callable=AsyncMock,
        ) as mock_add_review_tags,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
    ):
        await service.batch_add_file_tags(137, [10], [1], [])

    mock_add_tags.assert_awaited_once_with([1], "10", ResourceTypeEnum.SPACE_FILE, 1)
    mock_add_review_tags.assert_not_awaited()


@pytest.mark.asyncio
async def test_partition_file_tag_ids_routes_review_ids_when_not_present_in_tag_table(service):
    """Pending ids misclassified into tag_ids move to review only when they are not Tags."""
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
    ) as mock_session_ctx:
        session = AsyncMock()
        session.exec = AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: []),  # Tag.id in (...) -> none are Tags
                SimpleNamespace(all=lambda: [101, 102, 103]),  # ReviewTag.id in (...) -> genuine review tags
            ]
        )
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        tag_ids, review_tag_ids = await service._partition_file_tag_ids_for_update(
            [101, 102, 103],
            [],
        )

    assert tag_ids == []
    assert review_tag_ids == [101, 102, 103]

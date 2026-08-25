"""Tests for TagLibraryTagService.append_file_library_tags_sync."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def _make_session(*, existing_tag=None):
    session = MagicMock()
    find_result = MagicMock()
    find_result.all.return_value = [existing_tag] if existing_tag is not None else []
    link_result = MagicMock()
    link_result.all.return_value = []
    session.exec.side_effect = [find_result, link_result]
    return session


@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.get_sync_db_session",
)
@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge",
    return_value=[10],
)
def test_append_file_library_tags_creates_tag_in_first_library(mock_list_libs, mock_session_ctx):
    session = _make_session()
    mock_session_ctx.return_value.__enter__.return_value = session

    created_objects: list[object] = []

    def fake_add(obj):
        if getattr(obj, "name", None):
            obj.id = 100
        created_objects.append(obj)

    session.add.side_effect = fake_add

    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_service.request_file_sync_intents_sync",
    ) as request_fulltext_sync:
        TagLibraryTagService.append_file_library_tags_sync(
            space_id=137,
            file_id=42,
            tag_names=["新标签"],
            user_id=1,
            tenant_id=1,
            resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
        )

    assert len(created_objects) == 2
    tag_row = created_objects[0]
    link_row = created_objects[1]
    assert tag_row.name == "新标签"
    assert tag_row.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value
    assert tag_row.business_id == "10"
    assert tag_row.resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value
    assert link_row.tag_id == 100
    assert link_row.resource_id == "42"
    assert link_row.resource_type == ResourceTypeEnum.SPACE_FILE.value
    mock_list_libs.assert_called_once_with(137)
    request_fulltext_sync.assert_called_once()
    session.commit.assert_called_once()


@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.get_sync_db_session",
)
@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge",
    return_value=[10],
)
def test_append_file_library_tags_reuses_existing_tag_without_insert(mock_list_libs, mock_session_ctx):
    session = _make_session()
    existing = SimpleNamespace(
        id=55,
        name="已有标签",
        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
        business_id="99",
    )
    session = _make_session(existing_tag=existing)
    mock_session_ctx.return_value.__enter__.return_value = session

    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_service.request_file_sync_intents_sync",
    ) as request_fulltext_sync:
        TagLibraryTagService.append_file_library_tags_sync(
            space_id=137,
            file_id=42,
            tag_names=["已有标签"],
            user_id=1,
            tenant_id=1,
            resource_type=TagResourceTypeEnum.SYSTEM_TAG,
        )

    session.add.assert_called_once()
    link_row = session.add.call_args.args[0]
    assert link_row.tag_id == 55
    request_fulltext_sync.assert_called_once()
    session.flush.assert_not_called()


@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.get_sync_db_session",
)
@patch(
    "bisheng.knowledge.domain.services.tag_library_tag_service.KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge",
    return_value=[],
)
def test_append_file_library_tags_skips_unknown_when_space_has_no_library(mock_list_libs, mock_session_ctx):
    session = _make_session()
    mock_session_ctx.return_value.__enter__.return_value = session

    with (
        patch.object(TagLibraryTagService, "_first_library_id_for_space", return_value=None),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.request_file_sync_intents_sync",
        ) as request_fulltext_sync,
    ):
        TagLibraryTagService.append_file_library_tags_sync(
            space_id=137,
            file_id=42,
            tag_names=["孤立标签"],
            user_id=1,
            tenant_id=1,
            resource_type=TagResourceTypeEnum.SYSTEM_TAG,
        )

    session.add.assert_not_called()
    request_fulltext_sync.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_and_append_file_tags_skips_when_space_unbound():
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
        new=AsyncMock(return_value=[]),
    ) as list_libs:
        applied = await TagLibraryTagService.ensure_and_append_file_tags(
            space_id=137,
            file_id=42,
            tag_names=["孤立标签"],
            user_id=1,
            tenant_id=1,
        )

    assert applied == []
    list_libs.assert_awaited_once_with(137)


@pytest.mark.asyncio
async def test_ensure_and_append_file_tags_reuses_existing_and_creates_missing():
    existing = SimpleNamespace(id=55, name="已有标签")
    created = SimpleNamespace(id=100, name="新标签")

    with (
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new=AsyncMock(return_value=[10]),
        ),
        patch.object(TagLibraryTagService, "count_tags", new=AsyncMock(return_value=2)),
        patch.object(
            TagLibraryTagService,
            "find_library_tag_by_name",
            new=AsyncMock(side_effect=[existing, None]),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagDao.ainsert_tag",
            new=AsyncMock(return_value=created),
        ) as insert_tag,
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagDao.add_tags",
            new=AsyncMock(return_value=True),
        ) as add_links,
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.get_async_db_session",
        ) as session_ctx,
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.request_file_sync_intents",
            new=AsyncMock(),
        ),
        patch.object(TagLibraryTagService, "sync_library_name_lists", new=AsyncMock()) as sync_names,
        patch.object(
            TagLibraryTagService,
            "invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
    ):
        session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
        applied = await TagLibraryTagService.ensure_and_append_file_tags(
            space_id=137,
            file_id=42,
            tag_names=["已有标签", "新标签"],
            user_id=1,
            tenant_id=1,
        )

    assert applied == ["已有标签", "新标签"]
    insert_tag.assert_awaited_once()
    assert insert_tag.await_args.args[0].business_id == "10"
    add_links.assert_awaited_once()
    assert add_links.await_args.args[0] == [55, 100]
    sync_names.assert_awaited_once_with(10)

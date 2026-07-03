"""Tests for TagLibraryTagService.append_file_library_tags_sync."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def _make_session(*, existing_tag=None):
    session = MagicMock()
    find_result = MagicMock()
    find_result.first.return_value = existing_tag
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

    TagLibraryTagService.append_file_library_tags_sync(
        space_id=137,
        file_id=42,
        tag_names=["孤立标签"],
        user_id=1,
        tenant_id=1,
        resource_type=TagResourceTypeEnum.SYSTEM_TAG,
    )

    session.add.assert_not_called()
    session.commit.assert_not_called()

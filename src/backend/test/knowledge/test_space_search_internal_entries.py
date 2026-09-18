"""库内搜索不得把投影清理记录当成文件返回。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.fixture
async def search_service(async_db_session, monkeypatch):
    rows = [
        (101, None, None), (102, "manager", "active"),
        (103, "publish", "active"), (104, "share", "active"),
        (105, "share", "invalid"), (110, None, None),
        (111, None, None), (112, None, None),
        (201, "projection_tombstone", "preparing"),
        (202, "projection_tombstone", "deleting"),
        (203, "publish", "preparing"), (204, "share", "deleting"),
    ]
    for file_id, entry_type, entry_status in rows:
        async_db_session.add(KnowledgeFile(
            id=file_id, knowledge_id=3637, file_name="北京管理办法.doc",
            file_type=1, status=2, file_level_path="/10",
            reference_document_id=900 if entry_type else None,
            entry_type=entry_type, entry_status=entry_status,
        ))
    async_db_session.add(KnowledgeFile(
        id=205, knowledge_id=3637, file_name="仅清理记录.doc", file_type=1,
        entry_type="projection_tombstone", entry_status="deleting",
    ))
    async_db_session.add(KnowledgeFile(
        id=10, knowledge_id=3637, file_name="目录", file_type=2, file_level_path="",
    ))
    async_db_session.add(KnowledgeFile(
        id=106, knowledge_id=3637, file_name="北京其它目录.doc", file_type=1,
        status=2, file_level_path="/20",
    ))
    await async_db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield async_db_session

    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session", session_factory)
    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge_space_file.get_async_db_session", session_factory)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids",
        AsyncMock(return_value=[112]),
    )
    svc = object.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=1)
    svc._entry_permission_ids_by_file = {}
    svc._portal_file_download_map = {}
    svc.version_repo = SimpleNamespace(find_non_primary_file_ids=AsyncMock(return_value=[111]))
    svc._require_read_permission = AsyncMock(return_value=SimpleNamespace(id=3637))
    svc._require_permission_id = AsyncMock()
    svc._require_folder_relation = AsyncMock(return_value=SimpleNamespace(id=10, file_level_path=""))
    svc._resolve_folder_stats_keyword_file_ids = AsyncMock(return_value=[])
    svc._resolve_folder_stats_tag_file_ids = AsyncMock(return_value=None)
    svc._build_child_permission_context = AsyncMock(return_value={"can_view_all_statuses": True})

    async def permissions(item, **kwargs):
        return set() if item.id == 110 else {"view_file", "delete_file"}

    svc._get_child_item_effective_permission_ids = permissions
    svc._enrich_with_version_info = AsyncMock()

    async def enrich(items, **kwargs):
        for item in items:
            KnowledgeDocumentEntryResolver._capabilities(
                item.entry_type or "normal", {"view_file"}, allow_download=True,
            )
        return [{"id": item.id} for item in items]

    svc._handle_file_folder_extra_info = enrich
    return svc


@pytest.mark.parametrize("parent_id", [None, 10])
@pytest.mark.parametrize("page_size", [1, 20])
async def test_search_hides_internal_entries_before_count_and_paging(search_service, parent_id, page_size):
    expected = {101, 102, 103, 104, 105} | ({106} if parent_id is None else set())
    ids = []
    for page in range(1, (len(expected) + page_size - 1) // page_size + 1):
        result = await search_service.search_space_children(
            3637, parent_id=parent_id, keyword="北京", page=page, page_size=page_size,
            order_field="id", order_sort="asc",
        )
        assert result["total"] == len(expected)
        ids.extend(item["id"] for item in result["data"])
    assert len(ids) == len(set(ids)) == len(expected)
    assert set(ids) == expected


async def test_search_only_internal_matches_returns_successful_empty_page(search_service):
    result = await search_service.search_space_children(3637, keyword="仅清理记录")
    assert result["total"] == 0
    assert result["data"] == []


async def test_filtered_folder_counts_exclude_internal_entries(search_service):
    counts = await search_service._load_filtered_folder_stat_counts(
        space=SimpleNamespace(id=3637),
        folders=[SimpleNamespace(id=10, file_level_path="")], keyword="北京",
    )
    assert counts[10]["file_num"] == 6
    assert counts[10]["visible_success_file_num"] == 5


async def test_tag_search_still_filters_candidates_and_permissions(search_service, monkeypatch):
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.TagDao.aget_resources_by_tags",
        AsyncMock(return_value=[SimpleNamespace(resource_id=i) for i in [101, 110, 201]]),
    )
    result = await search_service.search_space_children(3637, keyword="北京", tag_ids=[7])
    assert result["total"] == 1
    assert result["data"] == [{"id": 101}]


async def test_regular_list_keeps_invalid_entries_but_hides_internal_entries(search_service):
    items = await SpaceFileDao.async_list_children(3637, parent_id=10, exclude_file_ids=[111, 112])
    assert {item.id for item in items} == {101, 102, 103, 104, 105, 110}

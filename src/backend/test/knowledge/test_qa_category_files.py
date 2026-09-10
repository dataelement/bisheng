from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def request(**kwargs):
    return SimpleNamespace(
        space_ids=[10],
        discovery_scope="legacy",
        stats_only=False,
        document_type="ZC",
        file_subcategory_code=None,
        cursor=None,
        page_size=1,
        **kwargs,
    )


async def test_category_counts_cover_unloaded_pages_and_parent_scope():
    service = object.__new__(KnowledgeSpaceService)
    files = [
        SimpleNamespace(id=i, knowledge_id=10, file_subcategory_code=sub) for i, sub in [(3, "A"), (2, "B"), (1, "")]
    ]
    service._load_qa_category_files = AsyncMock(return_value=(files, {10: "公共库"}))
    service._get_shougang_document_type_code = lambda _: "ZC"
    req = request()
    req.stats_only = True
    result = await service.get_shougang_portal_qa_category_files(req)
    assert result["counts"] == {"l1:ZC": 3, "l2:ZC:A": 1, "l2:ZC:B": 1}
    assert result["data"] == []


async def test_category_loader_reuses_space_and_file_permissions_and_excludes_old_files():
    service = object.__new__(KnowledgeSpaceService)
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[SimpleNamespace(id=10, name="库")])
    service._require_read_permission = AsyncMock()
    service.version_repo = SimpleNamespace(find_non_primary_file_ids_by_knowledge_ids=AsyncMock(return_value=[2]))
    files = [SimpleNamespace(id=i, knowledge_id=10, file_type=1, status=2) for i in [1, 2, 3, 4]]
    service._filter_visible_child_items = AsyncMock(return_value=[files[0]])
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters",
            AsyncMock(return_value=files),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids",
            AsyncMock(return_value=[3]),
        ),
    ):
        result, _ = await service._load_qa_category_files(request())
    assert result == [files[0]]
    service._require_read_permission.assert_awaited_once_with(10)
    service._filter_visible_child_items.assert_awaited_once_with([files[0], files[3]], space_id=10)


async def test_empty_category_scope_never_falls_back_to_all_spaces():
    service = object.__new__(KnowledgeSpaceService)
    service._get_shougang_portal_request_spaces = AsyncMock()
    req = request()
    req.space_ids = []
    assert await service._load_qa_category_files(req) == ([], {})
    service._get_shougang_portal_request_spaces.assert_not_awaited()


async def test_denied_space_stops_before_loading_any_files():
    service = object.__new__(KnowledgeSpaceService)
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[SimpleNamespace(id=10, name="库")])
    service._require_read_permission = AsyncMock(side_effect=PermissionError("denied"))
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters",
        AsyncMock(),
    ) as load:
        with pytest.raises(PermissionError):
            await service._load_qa_category_files(request())
        load.assert_not_awaited()

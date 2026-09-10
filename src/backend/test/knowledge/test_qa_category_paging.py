from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalQaCategoryFilesReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def make_service(denied=()):
    service = object.__new__(KnowledgeSpaceService)
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[SimpleNamespace(id=10, name="公共库")])
    service._require_read_permission = AsyncMock()
    service.version_repo = None
    service._load_qa_category_files = AsyncMock(side_effect=AssertionError("列表不应触发全量统计"))
    service._filter_visible_child_items = AsyncMock(
        side_effect=lambda files, **_: [f for f in files if f.id not in denied]
    )
    service._handle_file_folder_extra_info = AsyncMock(side_effect=lambda files: [vars(f) for f in files])
    service._map_shougang_portal_file_item = lambda sid, item: item

    async def load(**kwargs):
        start = min(kwargs["before_id"] or 10001, 10001) - 1
        return [
            SimpleNamespace(id=i, knowledge_id=10, file_encoding="SG-ZC-A-001", file_subcategory_code="A")
            for i in range(start, max(start - kwargs["limit"], 0), -1)
        ]

    service.knowledge_file_repo = SimpleNamespace(list_qa_category_candidates=AsyncMock(side_effect=load))
    return service


async def test_large_category_page_never_loads_all_ten_thousand_files():
    service = make_service(denied={10000})
    req = ShougangPortalQaCategoryFilesReq(space_ids=[10], document_type="ZC", file_subcategory_code="A", page_size=20)
    with patch(
        "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids",
        AsyncMock(return_value=[]),
    ):
        first = await service.get_shougang_portal_qa_category_files(req)
        req.cursor = first["next_cursor"]
        second = await service.get_shougang_portal_qa_category_files(req)
    assert [f["id"] for f in first["data"]] == list(range(9999, 9979, -1))
    assert [f["id"] for f in second["data"]] == list(range(9979, 9959, -1))
    assert first["counts"] == {}
    assert first["has_more"] is True
    assert service.knowledge_file_repo.list_qa_category_candidates.await_count == 2
    assert max(len(call.args[0]) for call in service._filter_visible_child_items.await_args_list) <= 50
    assert service._handle_file_folder_extra_info.await_args.args[0][0].id == 9979
    service._load_qa_category_files.assert_not_awaited()


async def test_denied_candidates_have_bounded_work_and_a_progressing_cursor():
    service = make_service(denied=set(range(1, 10001)))
    req = ShougangPortalQaCategoryFilesReq(space_ids=[10], document_type="ZC", page_size=20)
    with patch(
        "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids",
        AsyncMock(return_value=[]),
    ):
        result = await service.get_shougang_portal_qa_category_files(req)
    assert result["data"] == []
    assert result["has_more"] is True
    assert int(result["next_cursor"]) < 10000
    assert service.knowledge_file_repo.list_qa_category_candidates.await_count == 5

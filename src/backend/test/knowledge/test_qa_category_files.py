from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.parametrize("space_count", [241, 1000])
@pytest.mark.parametrize("stats_only", [False, True])
def test_category_request_preserves_large_space_scope(space_count, stats_only):
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalQaCategoryFilesReq

    space_ids = list(range(1, space_count + 1))
    req = ShougangPortalQaCategoryFilesReq(space_ids=space_ids, stats_only=stats_only)
    assert req.space_ids == space_ids
    assert req.stats_only is stats_only


def request(**kwargs):
    return SimpleNamespace(
        space_ids=[10],
        discovery_scope="legacy",
        stats_only=False,
        document_type=None,
        file_subcategory_code=None,
        cursor=None,
        page_size=1,
        **kwargs,
    )


async def test_category_counts_cover_unloaded_pages_and_parent_scope():
    service = object.__new__(KnowledgeSpaceService)
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
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


async def test_scoped_category_counts_filter_before_permissions_without_page_limit():
    service = object.__new__(KnowledgeSpaceService)
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[SimpleNamespace(id=10, name="库")])
    service._require_read_permission = AsyncMock()
    service.version_repo = None
    rows = [
        SimpleNamespace(id=i, knowledge_id=10, file_type=1, status=2,
                        file_encoding="SG-ZC-A-001", file_subcategory_code="A")
        for i in range(1, 206)
    ]
    # SQL 编码包含匹配可能命中其他分段，服务层仍须精确校验分类。
    other = SimpleNamespace(id=999, knowledge_id=10, file_type=1, status=2,
                            file_encoding="SG-BG-ZC-001", file_subcategory_code="A")
    service.knowledge_file_repo = SimpleNamespace(
        list_qa_category_candidates=AsyncMock(return_value=[*rows, other]),
    )
    service._filter_visible_child_items = AsyncMock(side_effect=lambda files, **kw: files[:-1])
    req = request()
    req.stats_only, req.document_type, req.file_subcategory_code = True, "ZC", "A"
    with (
        patch('bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters',
              AsyncMock(side_effect=AssertionError("分类统计不得读取全库文件"))),
        patch('bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids',
              AsyncMock(return_value=[])),
    ):
        result = await service.get_shougang_portal_qa_category_files(req)
    assert result['counts'] == {'l1:ZC': 204, 'l2:ZC:A': 204}
    service._filter_visible_child_items.assert_awaited_once_with(rows, space_id=10)
    service.knowledge_file_repo.list_qa_category_candidates.assert_awaited_once_with(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=None, limit=None,
    )


async def test_category_loader_reuses_space_and_file_permissions_and_excludes_old_files():
    service = object.__new__(KnowledgeSpaceService)
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
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
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
    service._get_shougang_portal_request_spaces = AsyncMock()
    req = request()
    req.space_ids = []
    assert await service._load_qa_category_files(req) == ([], {})
    service._get_shougang_portal_request_spaces.assert_not_awaited()


async def test_denied_space_stops_before_loading_any_files():
    service = object.__new__(KnowledgeSpaceService)
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=[SimpleNamespace(id=10, name="库")])
    service._require_read_permission = AsyncMock(side_effect=PermissionError("denied"))
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters",
        AsyncMock(),
    ) as load:
        with pytest.raises(PermissionError):
            await service._load_qa_category_files(request())
        load.assert_not_awaited()


@pytest.mark.parametrize("stats_only", [True, False])
@pytest.mark.parametrize("case", ["mixed", "all_denied", "service_failure"])
async def test_category_scope_isolates_stale_spaces_but_propagates_service_failure(stats_only, case):
    from bisheng.common.errcode.knowledge_space import SpaceNotFoundError, SpacePermissionDeniedError

    service = object.__new__(KnowledgeSpaceService)
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), None) for sid in ids])
    spaces = [SimpleNamespace(id=sid, name=str(sid)) for sid in [20, 30, 10]]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)

    async def readable(sid):
        if case == "service_failure":
            raise RuntimeError("FGA unavailable")
        if sid == 20:
            raise SpaceNotFoundError()
        if sid == 30 or case == "all_denied":
            raise SpacePermissionDeniedError()

    service._require_read_permission = AsyncMock(side_effect=readable)
    service.version_repo = None
    rows = [SimpleNamespace(id=fid, knowledge_id=sid, file_type=1, status=2)
            for fid, sid in [(9, 20), (8, 30), (7, 10), (6, 10)]]
    service._filter_visible_child_items = AsyncMock(side_effect=lambda files, **kw: [f for f in files if f.id == 7])
    service._get_shougang_document_type_code = lambda f: "ZC"
    service._get_shougang_file_subcategory_code = lambda f: ""
    service._filter_shougang_portal_files_by_document_type = lambda rows, code: rows
    service._filter_shougang_portal_files_by_subcategory_code = lambda rows, code: rows
    service._handle_file_folder_extra_info = AsyncMock(side_effect=lambda files: [vars(f) for f in files])
    service._map_shougang_portal_file_item = lambda sid, item: item
    service.knowledge_file_repo = SimpleNamespace(list_qa_category_candidates=AsyncMock(return_value=rows))
    load = AsyncMock(side_effect=lambda **kw: [f for f in rows if f.knowledge_id in kw['knowledge_ids']])
    req = request()
    req.space_ids, req.stats_only = [20, 30, 10], stats_only
    with (
        patch('bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_space_filters', load),
        patch('bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids', AsyncMock(return_value=[])),
    ):
        if case == "service_failure":
            with pytest.raises(RuntimeError, match="FGA unavailable"):
                await service.get_shougang_portal_qa_category_files(req)
            return
        result = await service.get_shougang_portal_qa_category_files(req)
    assert result['counts'] == ({'l1:ZC': 1} if stats_only and case == 'mixed' else {})
    assert [f['id'] for f in result['data']] == ([7] if not stats_only and case == 'mixed' else [])
    assert result['has_more'] is False
    assert [call.args[0] for call in service._require_read_permission.await_args_list] == [20, 30, 10]
    assert all(call.kwargs['space_id'] == 10 for call in service._filter_visible_child_items.await_args_list)
    if stats_only:
        if case == 'mixed':
            assert load.await_args.kwargs['knowledge_ids'] == [10]
        else:
            load.assert_not_awaited()

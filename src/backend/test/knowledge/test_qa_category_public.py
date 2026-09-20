from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalQaCategoryFilesReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def make_service(rows, levels):
    service = object.__new__(KnowledgeSpaceService)
    service.version_repo = None
    service._portal_file_download_map = {}
    service._entry_permission_ids_by_file = {}
    service._portal_file_access_decision_map = {}
    service._portal_unchecked_department_file_ids = set()
    service._load_qa_category_space_metadata = AsyncMock(
        side_effect=lambda ids: [(SimpleNamespace(id=sid, name=str(sid)), levels[sid])
                                 for sid in ids if sid in levels])
    service._get_shougang_portal_request_spaces = AsyncMock(
        side_effect=lambda **kw: [SimpleNamespace(id=sid, name=str(sid)) for sid in kw['requested_space_ids']])
    service._require_read_permission = AsyncMock()
    service._filter_visible_child_items = AsyncMock(side_effect=lambda files, **kw: files)
    service._handle_file_folder_extra_info = AsyncMock(side_effect=lambda files: [vars(f) for f in files])
    service._map_shougang_portal_file_item = lambda sid, item: item
    service.knowledge_file_repo = SimpleNamespace(list_qa_category_candidates=AsyncMock(return_value=rows))
    return service


def file(fid, sid, encoding='SG-ZC-A-001'):
    return SimpleNamespace(id=fid, knowledge_id=sid, file_type=1, status=2,
                           file_encoding=encoding, file_subcategory_code='A')


@pytest.mark.parametrize('stats_only', [True, False])
@pytest.mark.parametrize('discovery_scope', ['legacy', 'public'])
async def test_public_category_needs_no_user_permissions_or_recycle_query(stats_only, discovery_scope):
    service = make_service([file(3, 10), file(2, 10), file(1, 10)], {10: 'public'})
    service.version_repo = SimpleNamespace(find_non_primary_file_ids_by_knowledge_ids=AsyncMock(return_value=[2]))
    service._require_read_permission.side_effect = AssertionError('公共读取不应计算空间权限')
    service._filter_visible_child_items.side_effect = AssertionError('公共读取不应计算文件权限')
    service._get_shougang_portal_request_spaces.side_effect = AssertionError('公共读取不应解析用户可见范围')
    with patch('bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeRecycleService.list_recycled_file_ids',
               AsyncMock(side_effect=AssertionError('SQL 已排除删除文件'))):
        result = await service.get_shougang_portal_qa_category_files(ShougangPortalQaCategoryFilesReq(
            space_ids=list(range(1, 101)), document_type='ZC', stats_only=stats_only,
            discovery_scope=discovery_scope, page_size=20))
    assert result['counts'] == ({'l1:ZC': 2, 'l2:ZC:A': 2} if stats_only else {})
    assert [item['id'] for item in result['data']] == ([] if stats_only else [3, 1])
    service._load_qa_category_space_metadata.assert_awaited_once_with([10])
    service.version_repo.find_non_primary_file_ids_by_knowledge_ids.assert_awaited_once_with([10])


async def test_stats_prepares_only_exact_matching_spaces_and_keeps_private_authorization():
    service = make_service([file(3, 10), file(2, 20), file(1, 30, 'SG-BG-ZC-001')],
                           {10: 'public', 20: 'personal', 30: 'personal'})
    service._filter_visible_child_items.return_value = []
    service._filter_visible_child_items.side_effect = None
    result = await service.get_shougang_portal_qa_category_files(ShougangPortalQaCategoryFilesReq(
        space_ids=list(range(1, 101)), document_type='ZC', stats_only=True))
    assert result['counts'] == {'l1:ZC': 1, 'l2:ZC:A': 1}
    service._load_qa_category_space_metadata.assert_awaited_once_with([10, 20])
    service._require_read_permission.assert_awaited_once_with(20)
    assert service._get_shougang_portal_request_spaces.await_args.kwargs['requested_space_ids'] == [20]
    assert service._filter_visible_child_items.await_args.kwargs['space_id'] == 20


async def test_empty_exact_category_returns_without_space_preparation():
    service = make_service([file(1, 10, 'SG-BG-ZC-001')], {10: 'public'})
    result = await service.get_shougang_portal_qa_category_files(ShougangPortalQaCategoryFilesReq(
        space_ids=[10], document_type='ZC', stats_only=True))
    assert result['counts'] == {}
    service._load_qa_category_space_metadata.assert_not_awaited()


async def test_public_becoming_private_is_rechecked_and_unknown_errors_are_not_zero_counts():
    levels = {10: 'public'}
    service = make_service([file(1, 10)], levels)
    req = ShougangPortalQaCategoryFilesReq(space_ids=[10], document_type='ZC', stats_only=True)
    assert (await service.get_shougang_portal_qa_category_files(req))['counts']['l1:ZC'] == 1
    levels[10] = 'personal'
    service._require_read_permission.side_effect = SpacePermissionDeniedError()
    assert (await service.get_shougang_portal_qa_category_files(req))['counts'] == {}
    service._require_read_permission.side_effect = RuntimeError('FGA unavailable')
    with pytest.raises(RuntimeError, match='FGA unavailable'):
        await service.get_shougang_portal_qa_category_files(req)
    req.discovery_scope = 'public'
    service._require_read_permission.reset_mock()
    assert (await service.get_shougang_portal_qa_category_files(req))['counts'] == {}
    service._require_read_permission.assert_not_awaited()


async def test_file_refs_skip_enrichment_and_preserve_empty_page_cursor():
    service = make_service([file(3, 10), file(2, 10), file(1, 10)], {10: 'department'})
    service._portal_file_access_decision_map = {
        3: SimpleNamespace(status='approval_required'),
        2: SimpleNamespace(status='allowed'),
    }
    service._portal_unchecked_department_file_ids = {1}
    service._handle_file_folder_extra_info.side_effect = AssertionError('引用不应补全展示信息')
    req = ShougangPortalQaCategoryFilesReq(space_ids=[10], document_type='ZC', page_size=1)
    first = await service.get_shougang_portal_qa_category_file_refs(req)
    assert first == {'data': [], 'has_more': True, 'next_cursor': '3'}
    req.cursor = first['next_cursor']
    service.knowledge_file_repo.list_qa_category_candidates.return_value = [file(2, 10), file(1, 10)]
    second = await service.get_shougang_portal_qa_category_file_refs(req)
    assert second == {'data': [{'space_id': 10, 'file_id': 2}], 'has_more': True, 'next_cursor': '2'}
    req.cursor = second['next_cursor']
    service.knowledge_file_repo.list_qa_category_candidates.return_value = [file(1, 10)]
    assert await service.get_shougang_portal_qa_category_file_refs(req) == {
        'data': [], 'has_more': False, 'next_cursor': None}
    service._handle_file_folder_extra_info.assert_not_awaited()


async def test_public_refs_match_list_entries_without_file_permissions():
    service = make_service([file(3, 10), file(2, 10), file(1, 10)], {10: 'public'})
    service.version_repo = SimpleNamespace(find_non_primary_file_ids_by_knowledge_ids=AsyncMock(return_value=[2]))
    service._require_read_permission.side_effect = AssertionError('公共空间权限计算')
    service._filter_visible_child_items.side_effect = AssertionError('公共文件权限计算')
    req = ShougangPortalQaCategoryFilesReq(space_ids=[10], document_type='ZC')
    listing = await service.get_shougang_portal_qa_category_files(req)
    service._handle_file_folder_extra_info.reset_mock()
    refs = await service.get_shougang_portal_qa_category_file_refs(req)
    assert refs['data'] == [{'space_id': f['knowledge_id'], 'file_id': f['id']} for f in listing['data']]
    service._handle_file_folder_extra_info.assert_not_awaited()

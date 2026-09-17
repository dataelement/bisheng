"""分类浏览使用数据库。独立的全文检索功能保留原有行为。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileCountReq,
    ShougangPortalFileSearchReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.parametrize("keyword", ["资金管理", "   "])
async def test_category_search_uses_semantic_retrieval_only_with_keyword(keyword):
    """搜索保留分类范围。清空关键词后恢复数据库浏览。"""
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=1)]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service._get_shougang_portal_tag_file_ids = AsyncMock(return_value=None)
    semantic_result = {"data": [{"id": 11}], "has_more": False, "next_cursor": None}
    browse_result = {"data": [{"id": 22}], "has_more": False, "next_cursor": None}
    service._semantic_search_shougang_portal_files = AsyncMock(return_value=semantic_result)
    service.browse_shougang_portal_files = AsyncMock(return_value=browse_result)
    service.advanced_search_shougang_portal_files = AsyncMock(
        side_effect=AssertionError("分类搜索不应切换为高级全文检索")
    )
    req = ShougangPortalFileSearchReq(
        q=keyword,
        document_type="POL",
        discovery_scope="portal_enabled",
        retrieval_profile="portal_global_shared" if keyword.strip() else "legacy",
    )

    result = await service.search_shougang_portal_files(req)

    if keyword.strip():
        assert result == semantic_result
        service.browse_shougang_portal_files.assert_not_awaited()
        forwarded = service._semantic_search_shougang_portal_files.await_args.kwargs["req"]
        assert forwarded.q == keyword
        assert forwarded.retrieval_profile == "portal_global_shared"
    else:
        assert result == browse_result
        service._semantic_search_shougang_portal_files.assert_not_awaited()
        forwarded = service.browse_shougang_portal_files.await_args.args[0]
    assert forwarded.document_type == "POL"
    assert forwarded.discovery_scope == "portal_enabled"
    service.advanced_search_shougang_portal_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_without_keyword_reads_database_even_with_document_type(monkeypatch):
    """一级分类不改变业务库存的数据来源。"""
    service = object.__new__(KnowledgeSpaceService)
    service._portal_discovery_result = None
    routed = AsyncMock(return_value={"data": [], "has_more": False, "next_cursor": None})
    service._list_shougang_portal_files_via_fulltext_document_type = routed
    database = AsyncMock(return_value=[])
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_space_filters_cursor", database)

    req = ShougangPortalFileBrowseReq(document_type="NEW", limit=6)
    result = await KnowledgeSpaceService._list_shougang_portal_files_without_keyword(
        service,
        req=req,
        spaces=[SimpleNamespace(id=1)],
        tag_file_ids=None,
        trusted_public_scope=True,
    )

    assert result["data"] == []
    routed.assert_not_awaited()
    assert database.await_args.kwargs["document_type"] == "NEW"


@pytest.mark.asyncio
async def test_list_via_fulltext_document_type_delegates_to_advanced_search():
    """显式全文辅助函数保留高级检索委托及排序映射。"""
    service = object.__new__(KnowledgeSpaceService)
    advanced = AsyncMock(return_value={"data": [{"id": 1}], "has_more": False, "next_cursor": None})
    service.advanced_search_shougang_portal_files = advanced

    req = ShougangPortalFileBrowseReq(
        document_type="new",
        public_only=True,
        discovery_scope="public",
        sort="updated_at",
        limit=6,
    )
    result = await KnowledgeSpaceService._list_shougang_portal_files_via_fulltext_document_type(service, req)

    assert result["data"][0]["id"] == 1
    advanced.assert_awaited_once()
    advanced_req = advanced.await_args.args[0]
    assert isinstance(advanced_req, ShougangPortalAdvancedFileSearchReq)
    assert advanced_req.document_type == "NEW"
    assert advanced_req.sort == "updated_at_desc"
    assert advanced_req.public_only is True


def test_map_browse_sort_to_fulltext_sort():
    """排序别名映射到全文检索字面量。"""
    assert KnowledgeSpaceService._map_browse_sort_to_fulltext_sort("updated_at") == "updated_at_desc"
    assert KnowledgeSpaceService._map_browse_sort_to_fulltext_sort("updated_at_asc") == "updated_at_asc"
    assert KnowledgeSpaceService._map_browse_sort_to_fulltext_sort(None) == "updated_at_desc"


@pytest.mark.asyncio
async def test_count_browse_with_document_type_counts_exact_browse_pages(monkeypatch):
    """精确计数遵循浏览过滤结果。不直接累加 LIKE 候选。"""
    service = object.__new__(KnowledgeSpaceService)
    browse_mock = AsyncMock(
        side_effect=[
            {"data": [{"id": 1}], "has_more": True, "next_cursor": "cursor-1"},
            {"data": [{"id": 2}], "has_more": False, "next_cursor": None},
        ]
    )
    service.browse_shougang_portal_files = browse_mock
    service._portal_discovery_result = SimpleNamespace(snapshot="snap-1")

    acount_mock = AsyncMock(return_value=999)
    monkeypatch.setattr(KnowledgeFileDao, "acount_portal_files", acount_mock)

    req = ShougangPortalFileCountReq(
        query_type="browse",
        document_type="NEW",
        discovery_scope="portal_public",
    )
    result = await KnowledgeSpaceService.count_shougang_portal_files(service, req)

    assert result["total"] == 2
    assert result["discovery_snapshot"] == "snap-1"
    assert browse_mock.await_count == 2
    acount_mock.assert_not_awaited()

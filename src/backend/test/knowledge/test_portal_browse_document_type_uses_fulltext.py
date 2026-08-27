"""无关键词 browse 带 document_type 时应走 ES 全文检索，而非 MySQL LIKE。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileCountReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_list_without_keyword_routes_document_type_to_fulltext_helper():
    """用途：有 document_type 时短路到 ES 路径，避免 MySQL file_encoding LIKE。"""
    service = object.__new__(KnowledgeSpaceService)
    routed = AsyncMock(return_value={"data": [], "has_more": False, "next_cursor": None})
    service._list_shougang_portal_files_via_fulltext_document_type = routed

    req = ShougangPortalFileBrowseReq(document_type="NEW", limit=6)
    result = await KnowledgeSpaceService._list_shougang_portal_files_without_keyword(
        service,
        req=req,
        spaces=[SimpleNamespace(id=1)],
        tag_file_ids=None,
        trusted_public_scope=True,
    )

    assert result["data"] == []
    routed.assert_awaited_once_with(req)


@pytest.mark.asyncio
async def test_list_via_fulltext_document_type_delegates_to_advanced_search():
    """用途：document_type 浏览复用高级全文检索，并映射为 updated_at_desc。"""
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
    result = await KnowledgeSpaceService._list_shougang_portal_files_via_fulltext_document_type(
        service, req
    )

    assert result["data"][0]["id"] == 1
    advanced.assert_awaited_once()
    advanced_req = advanced.await_args.args[0]
    assert isinstance(advanced_req, ShougangPortalAdvancedFileSearchReq)
    assert advanced_req.document_type == "NEW"
    assert advanced_req.sort == "updated_at_desc"
    assert advanced_req.public_only is True


def test_map_browse_sort_to_fulltext_sort():
    """用途：browse 排序别名映射到全文检索字面量。"""
    assert (
        KnowledgeSpaceService._map_browse_sort_to_fulltext_sort("updated_at")
        == "updated_at_desc"
    )
    assert (
        KnowledgeSpaceService._map_browse_sort_to_fulltext_sort("updated_at_asc")
        == "updated_at_asc"
    )
    assert (
        KnowledgeSpaceService._map_browse_sort_to_fulltext_sort(None) == "updated_at_desc"
    )


@pytest.mark.asyncio
async def test_count_browse_with_document_type_paginates_browse_not_mysql(monkeypatch):
    """用途：document_type 计数与列表同走 browse/ES，避免 MySQL LIKE 虚高。"""
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

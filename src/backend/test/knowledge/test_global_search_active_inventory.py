"""Sidebar search must hide internal entries and historical versions before paging."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.parametrize("page_size", [1, 30])
async def test_global_search_returns_only_current_active_files(async_db_session, monkeypatch, page_size):
    name = "信息分级管理办法.doc"
    rows = [
        {"id": 101, "reference_document_id": 900, "entry_type": "manager", "entry_status": "active"},
        {"id": 102, "reference_document_id": 900, "entry_type": "projection_tombstone", "entry_status": "preparing"},
        {"id": 103, "reference_document_id": 900, "entry_type": "share", "entry_status": "invalid"},
        {"id": 104},
        {"id": 105, "deleted_at": datetime(2026, 9, 17)},
        {"id": 106, "reference_document_id": 900, "entry_type": "publish", "entry_status": "deleting"},
        {"id": 107, "reference_document_id": 900, "entry_type": "share", "entry_status": "preparing"},
        {"id": 108},
    ]
    for row in rows:
        async_db_session.add(KnowledgeFile(knowledge_id=19, file_name=name, file_type=1, status=2, **row))
    async_db_session.add(
        KnowledgeDocumentVersion(document_id=900, knowledge_file_id=104, version_no=1, is_primary=False)
    )
    async_db_session.add(
        KnowledgeDocumentVersion(document_id=900, knowledge_file_id=101, version_no=2, is_primary=True)
    )
    await async_db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield async_db_session

    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session", session_factory)
    service = object.__new__(KnowledgeSpaceService)
    service.get_grouped_spaces = AsyncMock(
        return_value=SimpleNamespace(
            public_spaces=[],
            department_spaces=[],
            team_spaces=[SimpleNamespace(id=19, name="智能制造室(制造)", space_level=KnowledgeSpaceLevelEnum.TEAM_KS)],
            personal_spaces=[],
        )
    )

    result = await service.global_search_files(keyword="信息分级", page_size=page_size)

    assert result["total"] == 2
    items = result["data"]
    if page_size == 1:
        second_page = await service.global_search_files(keyword="信息分级", page=2, page_size=page_size)
        assert second_page["total"] == 2
        items += second_page["data"]
    assert {item["file_id"] for item in items} == {101, 108}
    assert all(item["file_name"] == name and item["space_id"] == 19 for item in items)

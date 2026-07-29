from contextlib import asynccontextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import mysql

from bisheng.knowledge.domain.models import knowledge_file as knowledge_file_module
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalFileItemResp,
    ShougangPortalFileSearchReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_advanced_search_uses_database_dao_without_semantic_search():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=12, name="设备管理知识库")]
    files = [
        SimpleNamespace(
            id=101,
            knowledge_id=12,
            update_time=datetime(2025, 12, 31, 23, 59, 59),
        )
    ]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service._get_shougang_portal_tag_ids_for_spaces = AsyncMock(return_value=[7])
    service._filter_shougang_portal_search_files = AsyncMock(return_value=files)
    service._filter_shougang_portal_visible_files = AsyncMock(
        side_effect=AssertionError("登录检索不得执行部门文件权限校验")
    )
    service._map_shougang_portal_files_to_items = AsyncMock(
        return_value=[
            ShougangPortalFileItemResp(
                id=101,
                space_id=12,
                title="轧机振动故障排查.pdf",
            )
        ]
    )
    service._semantic_search_shougang_portal_files = AsyncMock(
        side_effect=AssertionError("高级检索不得调用 RAG 语义检索")
    )

    with patch.object(
        KnowledgeFileDao,
        "asearch_portal_advanced_cursor",
        new=AsyncMock(return_value=files),
    ) as database_search:
        result = await service.advanced_search_shougang_portal_files(
            ShougangPortalAdvancedFileSearchReq(
                discovery_scope="public_and_department",
                space_ids=[12],
                tag="振动",
                all_keywords="轧机 振动",
                search_field="file_name",
                updated_from=date(2025, 1, 1),
                updated_to=date(2025, 12, 31),
            )
        )

    database_search.assert_awaited_once()
    assert database_search.await_args.kwargs["knowledge_ids"] == [12]
    assert database_search.await_args.kwargs["tag_ids"] == [7]
    assert database_search.await_args.kwargs["status"] == [KnowledgeFileStatus.SUCCESS.value]
    service._filter_shougang_portal_search_files.assert_awaited_once_with(
        files,
        spaces=spaces,
        defer_department_access=True,
    )
    service._filter_shougang_portal_visible_files.assert_not_awaited()
    service._semantic_search_shougang_portal_files.assert_not_awaited()
    assert result["data"][0]["id"] == 101


@pytest.mark.asyncio
async def test_keyword_search_defers_department_access_during_recall():
    service = object.__new__(KnowledgeSpaceService)
    service._search_shougang_portal_es_chunks = AsyncMock(return_value=[])
    service._search_shougang_portal_vector_chunks = AsyncMock(return_value=[])
    service._filter_and_dedupe_portal_search_chunks = AsyncMock(return_value=[])

    result = await service._semantic_search_shougang_portal_files(
        req=ShougangPortalFileSearchReq(
            q="轧机振动",
            discovery_scope="public_and_department",
        ),
        spaces=[SimpleNamespace(id=12)],
        tag_file_ids=None,
    )

    service._filter_and_dedupe_portal_search_chunks.assert_awaited_once_with(
        chunks=[],
        spaces=[SimpleNamespace(id=12)],
        defer_department_access=True,
    )
    assert result["data"] == []


@pytest.mark.asyncio
async def test_search_file_filter_marks_department_files_without_access_lookup():
    service = object.__new__(KnowledgeSpaceService)
    service._portal_unchecked_department_file_ids = set()
    service._portal_file_download_map = {}
    service._get_shougang_portal_public_space_ids = AsyncMock(return_value=set())
    service._get_valid_department_space_ids = AsyncMock(return_value={12})
    service._filter_shougang_portal_visible_files = AsyncMock(
        side_effect=AssertionError("部门文件不应在检索阶段鉴权")
    )
    file = SimpleNamespace(id=101, knowledge_id=12)
    spaces = [SimpleNamespace(id=12)]

    result = await service._filter_shougang_portal_search_files(
        [file],
        spaces=spaces,
        defer_department_access=True,
    )

    assert result == [file]
    assert service._portal_unchecked_department_file_ids == {101}
    service._filter_shougang_portal_visible_files.assert_not_awaited()


def test_unchecked_department_search_result_keeps_metadata_and_requires_click_check():
    service = object.__new__(KnowledgeSpaceService)
    service._portal_unchecked_department_file_ids = {101}
    service._portal_file_access_decision_map = {}
    service._portal_file_download_map = {}

    result = service._map_shougang_portal_file_item(
        12,
        {
            "id": 101,
            "file_name": "轧机振动故障排查.pdf",
            "abstract": "完整检索摘要",
            "file_size": 1024,
            "source_path": "设备管理知识库/故障排查",
            "tags": [{"name": "振动"}],
        },
    )

    assert result.is_department_file is True
    assert result.content_access == "check_required"
    assert result.summary == "完整检索摘要"
    assert result.file_size == "1024"
    assert result.source_path == "设备管理知识库/故障排查"


@pytest.mark.asyncio
async def test_advanced_search_builds_mysql_multi_table_query(monkeypatch):
    captured_statements = []

    class FakeResult:
        @staticmethod
        def all():
            return []

    class FakeSession:
        async def exec(self, statement):
            captured_statements.append(statement)
            return FakeResult()

    @asynccontextmanager
    async def fake_session():
        yield FakeSession()

    monkeypatch.setattr(
        knowledge_file_module,
        "get_async_db_session",
        fake_session,
    )

    await KnowledgeFileDao.asearch_portal_advanced_cursor(
        knowledge_ids=[12],
        status=[KnowledgeFileStatus.SUCCESS.value],
        tag_ids=[7],
        all_keywords="轧机 振动",
        exact_phrase="故障排查",
        any_keywords="轴承 松动",
        exclude_keywords="招标",
        search_field="tags",
        updated_from=date(2025, 1, 1),
        updated_to=date(2025, 12, 31),
        limit=20,
    )

    assert len(captured_statements) == 1
    sql = str(
        captured_statements[0].compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "knowledgefile" in sql
    assert "taglink" in sql
    assert "knowledge_document" in sql
    assert "exists" in sql
    assert "2026-01-01" in sql
    assert "limit 20" in sql


def test_advanced_search_rejects_reversed_date_range():
    with pytest.raises(ValueError, match="updated_from must not be later"):
        ShougangPortalAdvancedFileSearchReq(
            updated_from=date(2025, 12, 31),
            updated_to=date(2025, 1, 1),
        )

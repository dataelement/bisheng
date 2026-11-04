from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import McpFolderRetrievalScopeLimitError, SpacePermissionDeniedError
from bisheng.knowledge.domain.services.knowledge_mcp_query_service import KnowledgeMcpQueryService


def make_service(count=0):
    from bisheng.knowledge.domain.services.knowledge_mcp_folder_retrieval_service import (
        KnowledgeMcpFolderRetrievalService,
    )

    rows = [SimpleNamespace(id=i, file_name=f"{i:05}.txt") for i in range(1, count + 1)]

    async def scan(space_ids, *, after=None, limit=100, **kwargs):
        assert space_ids == [118]
        assert kwargs == {
            "file_type": 1,
            "parent_path": "/305",
            "recursive": True,
            "statuses": [2],
            "sort_by": "file_name",
            "order": "asc",
        }
        return rows[(after[1] if after else 0) :][:limit]

    query = SimpleNamespace(
        require_space=AsyncMock(),
        folder_path=AsyncMock(return_value="/305"),
        repository=SimpleNamespace(scan_files=AsyncMock(side_effect=scan)),
        visible=AsyncMock(side_effect=lambda row: row.id % 2 == 1),
        file_key=KnowledgeMcpQueryService.file_key,
    )
    return KnowledgeMcpFolderRetrievalService(query), query


@pytest.mark.parametrize("count", [0, 101, 1000, 1001])
async def test_complete_scope_empty_and_capacity_boundary(count):
    """F083 覆盖 AC: AC-03, AC-04, AC-06;预算在权限过滤前计算。"""
    service, query = make_service(count)
    if count > 1000:
        with pytest.raises(McpFolderRetrievalScopeLimitError):
            await service.resolve_file_ids(knowledge_id=118, folder_id=305, recursive=True)
    else:
        result = await service.resolve_file_ids(knowledge_id=118, folder_id=305, recursive=True)
        assert result == list(range(1, count + 1, 2))
        if count == 1000:
            assert query.repository.scan_files.await_count == 11


@pytest.mark.parametrize("failure_stage", ["require_space", "folder_path", "visible"])
async def test_scope_rejects_before_search_and_propagates_permission_errors(failure_stage):
    """F083 覆盖 AC: AC-04, AC-06;拒绝和权限设施异常不能当作空目录。"""
    service, query = make_service(1)
    error = RuntimeError("permission unavailable") if failure_stage == "visible" else SpacePermissionDeniedError()
    getattr(query, failure_stage).side_effect = error
    with pytest.raises(type(error)):
        await service.resolve_file_ids(knowledge_id=118, folder_id=305, recursive=True)
    if failure_stage != "visible":
        query.repository.scan_files.assert_not_called()


async def test_scope_rejects_nonadvancing_inventory_page():
    """F083 覆盖 AC: AC-03, AC-06;异常分页不能产生部分成功或无限循环。"""
    service, query = make_service(100)
    query.repository.scan_files.side_effect = None
    query.repository.scan_files.return_value = [SimpleNamespace(id=i, file_name=f"{i:05}.txt") for i in range(1, 101)]
    with pytest.raises(ValueError):
        await service.resolve_file_ids(knowledge_id=118, folder_id=305, recursive=True)

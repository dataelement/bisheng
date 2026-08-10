from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParsePositionState,
    KnowledgeParseQueuePositionItem,
    KnowledgeParseQueuePositionsResponse,
    normalize_parse_queue_file_ids,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessDecision,
    DepartmentFileAccessSource,
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    KnowledgeFileVisibilityService,
)
from bisheng.knowledge.domain.services.knowledge_parse_queue_service import (
    KnowledgeParseQueueQueryService,
)


def _file(file_id: int, *, status: int = KnowledgeFileStatus.WAITING.value) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        user_id=7,
        knowledge_id=10,
        file_name=f"{file_id}.pdf",
        status=status,
    )


@pytest.mark.asyncio
async def test_query_service_omits_candidates_filtered_by_repository_or_visibility() -> None:
    candidate_files = [_file(1), _file(2)]
    file_repository = SimpleNamespace(find_by_ids_in_knowledge=AsyncMock(return_value=candidate_files))
    visibility_service = SimpleNamespace(filter_visible=AsyncMock(return_value=[candidate_files[0]]))
    authorization_service = SimpleNamespace(
        require_parse_queue_read=AsyncMock(return_value=SimpleNamespace(tenant_id=1))
    )
    expected = KnowledgeParseQueuePositionsResponse(
        items=[
            KnowledgeParseQueuePositionItem(
                file_id=1,
                state=KnowledgeParsePositionState.UNAVAILABLE,
            )
        ],
        active_count=0,
        as_of="2026-08-06T00:00:00Z",
    )
    queue_service = SimpleNamespace(get_positions=AsyncMock(return_value=expected))
    service = KnowledgeParseQueueQueryService(
        file_repository=file_repository,
        visibility_service=visibility_service,
        authorization_service=authorization_service,
        queue_service=queue_service,
        login_user=SimpleNamespace(user_id=7, tenant_id=1),
    )

    result = await service.query(knowledge_id=10, file_ids=[1, 2, 3, 999])

    assert result == expected
    file_repository.find_by_ids_in_knowledge.assert_awaited_once_with([1, 2, 3, 999], 10)
    queue_service.get_positions.assert_awaited_once_with(
        tenant_id=1,
        knowledge_id=10,
        files=[candidate_files[0]],
    )


@pytest.mark.asyncio
async def test_visibility_combines_standard_permissions_department_approval_and_hidden_status() -> None:
    files = [_file(index) for index in range(1, 6)]
    files[2].status = KnowledgeFileStatus.FAILED.value
    files[3].status = KnowledgeFileStatus.FAILED.value
    authorization_service = SimpleNamespace(filter_visible_files=AsyncMock(return_value=files[:4]))
    decisions = {
        1: DepartmentFileAccessDecision(
            file_id=1,
            space_id=10,
            status=DepartmentFileAccessStatus.NOT_APPLICABLE,
        ),
        2: DepartmentFileAccessDecision(
            file_id=2,
            space_id=10,
            status=DepartmentFileAccessStatus.APPROVAL_REQUIRED,
        ),
        3: DepartmentFileAccessDecision(
            file_id=3,
            space_id=10,
            status=DepartmentFileAccessStatus.ALLOWED,
            source=DepartmentFileAccessSource.RESOURCE_OWNER,
        ),
        4: DepartmentFileAccessDecision(
            file_id=4,
            space_id=10,
            status=DepartmentFileAccessStatus.ALLOWED,
            source=DepartmentFileAccessSource.PERMISSION_TEMPLATE,
        ),
        5: DepartmentFileAccessDecision(
            file_id=5,
            space_id=10,
            status=DepartmentFileAccessStatus.ALLOWED,
            source=DepartmentFileAccessSource.APPROVAL_GRANT,
        ),
    }
    department_service = SimpleNamespace(evaluate_files=AsyncMock(return_value=decisions))
    service = KnowledgeFileVisibilityService(
        authorization_service=authorization_service,
        department_access_service=department_service,
    )

    visible = await service.filter_visible(
        login_user=SimpleNamespace(user_id=7, tenant_id=1),
        knowledge_id=10,
        files=files,
    )

    assert [int(file.id) for file in visible] == [1, 3, 5]
    department_service.evaluate_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_visibility_dependency_failure_fails_closed() -> None:
    service = KnowledgeFileVisibilityService(
        authorization_service=SimpleNamespace(
            filter_visible_files=AsyncMock(side_effect=RuntimeError("fga unavailable"))
        ),
        department_access_service=SimpleNamespace(),
    )
    assert (
        await service.filter_visible(
            login_user=SimpleNamespace(user_id=7),
            knowledge_id=10,
            files=[_file(1)],
        )
        == []
    )


@pytest.mark.parametrize(
    ("knowledge_id", "file_ids"),
    [(0, [1]), (1, []), (1, [0]), (1, list(range(1, 102)))],
)
def test_endpoint_contract_rejects_invalid_bounded_ids(knowledge_id: int, file_ids: list[int]) -> None:
    with pytest.raises(ValueError, match="1 to 100 positive integers"):
        normalize_parse_queue_file_ids(knowledge_id, file_ids)


def test_endpoint_contract_deduplicates_ids() -> None:
    assert normalize_parse_queue_file_ids(10, [2, 2, 1]) == [2, 1]

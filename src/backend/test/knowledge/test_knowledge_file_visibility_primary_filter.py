"""Primary-version hard boundary for knowledge-space RAG retrieval."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    KnowledgeFileVisibilityService,
)


def _service(*, threshold: int) -> KnowledgeFileVisibilityService:
    service = KnowledgeFileVisibilityService(request=None, login_user=MagicMock())
    service._config = MagicMock(return_value=SimpleNamespace(index_filter_threshold=threshold))
    return service


async def _build_filter(
    *,
    primary_ids: set[int],
    non_primary_ids: set[int],
    visible_ids: set[int],
    threshold: int,
):
    service = _service(threshold=threshold)
    service._non_primary_ids = AsyncMock(return_value=non_primary_ids)
    service._list_primary_file_ids_in_space = AsyncMock(return_value=primary_ids)
    # These cases cover the primary-version boundary, not the file-change
    # approval guard; report nothing hidden rather than requiring a tenant.
    service._list_file_change_excluded_ids = AsyncMock(return_value=set())
    action_map = {str(file_id): frozenset({"visible"}) for file_id in visible_ids}
    with patch(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service.batch_check_business_actions",
        AsyncMock(return_value=action_map),
    ):
        result = await service.build_index_prefilter(10, None)
    service._list_primary_file_ids_in_space.assert_awaited_once_with(
        10,
        non_primary_ids=non_primary_ids,
    )
    return result


async def test_in_strategy_contains_only_visible_primary_ids():
    result = await _build_filter(
        primary_ids={1, 2, 3},
        non_primary_ids={9},
        visible_ids={1, 2},
        threshold=5,
    )

    assert result.strategy == "in"
    assert result.milvus_expr == "document_id in [1, 2]"
    assert result.es_filter == [{"terms": {"metadata.document_id": [1, 2]}}]


async def test_notin_strategy_excludes_non_primary_and_invisible_primary_ids():
    result = await _build_filter(
        primary_ids={1, 2, 3, 4},
        non_primary_ids={9},
        visible_ids={1, 2, 3},
        threshold=2,
    )

    assert result.strategy == "notin"
    assert result.milvus_expr == "document_id not in [4, 9]"
    assert result.es_filter == [
        {
            "bool": {
                "must_not": {
                    "terms": {"metadata.document_id": [4, 9]},
                }
            }
        }
    ]


async def test_none_strategy_has_primary_version_result_backstop():
    result = await _build_filter(
        primary_ids={1, 2, 3, 4, 5, 6, 7},
        non_primary_ids={9},
        visible_ids={1, 2, 3},
        threshold=2,
    )
    assert result.strategy == "none"

    service = _service(threshold=2)
    service.post_filter_visible_files = AsyncMock(return_value={1, 9})
    service._non_primary_ids = AsyncMock(return_value={9})

    permitted = await service.post_filter_retrievable_files(10, {1, 9})

    assert permitted == {1}
    service.post_filter_visible_files.assert_awaited_once_with(10, {1, 9})

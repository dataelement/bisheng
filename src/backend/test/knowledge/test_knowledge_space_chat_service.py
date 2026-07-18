"""Tests for KnowledgeSpaceChatService._build_folder_search_kwargs.

These tests exercise the primary-version-only filter injection logic in the
_build_folder_search_kwargs helper without invoking LLM or database calls.
We mock version_repo.find_non_primary_file_ids_by_knowledge_ids directly.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


def _make_service() -> KnowledgeSpaceChatService:
    """Construct a minimal KnowledgeSpaceChatService with a mocked version_repo."""
    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=MagicMock())
    svc.version_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Branch A — whole-space (target_file_ids is None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whole_space_with_non_primary_ids():
    """Branch A: version_repo returns [10, 20] -> milvus expr and ES must_not injected."""
    svc = _make_service()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[10, 20])

    milvus_kwargs, es_kwargs = await svc._build_folder_search_kwargs(
        knowledge_id=1,
        target_file_ids=None,
    )

    assert milvus_kwargs is not None
    assert es_kwargs is not None

    # Milvus expr must contain the not-in clause with sorted ids
    milvus_expr = milvus_kwargs["expr"]
    assert "document_id not in [10, 20]" in milvus_expr

    # ES filter must contain the must_not block
    es_filter = es_kwargs["filter"]
    assert {"bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}} in es_filter

    # Base k and ef values must be preserved
    assert milvus_kwargs["k"] == 100
    assert milvus_kwargs["param"] == {"ef": 110}
    assert es_kwargs["k"] == 100

    # Repo was called with the correct knowledge_id
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids.assert_awaited_once_with([1])


@pytest.mark.asyncio
async def test_whole_space_with_no_non_primary_ids():
    """Branch A: version_repo returns [] -> no expr or filter added (pre-change behavior)."""
    svc = _make_service()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[])

    milvus_kwargs, es_kwargs = await svc._build_folder_search_kwargs(
        knowledge_id=1,
        target_file_ids=None,
    )

    assert milvus_kwargs is not None
    assert es_kwargs is not None

    # No expr key when there is nothing to exclude
    assert "expr" not in milvus_kwargs

    # No filter key when there is nothing to exclude
    assert "filter" not in es_kwargs

    # Base k/ef preserved
    assert milvus_kwargs["k"] == 100
    assert milvus_kwargs["param"] == {"ef": 110}
    assert es_kwargs["k"] == 100


# ---------------------------------------------------------------------------
# Branch B — specific files (target_file_ids is not None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_specific_files_some_non_primary():
    """Branch B: target [5, 10, 20], excluded [10, 20] -> in-clause uses [5] only, no must_not."""
    svc = _make_service()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[10, 20])

    milvus_kwargs, es_kwargs = await svc._build_folder_search_kwargs(
        knowledge_id=1,
        target_file_ids=[5, 10, 20],
    )

    assert milvus_kwargs is not None
    assert es_kwargs is not None

    milvus_expr = milvus_kwargs["expr"]
    # Effective target is [5]; in-clause must reference only 5
    assert "[5]" in milvus_expr
    assert "document_id in" in milvus_expr
    # Non-primary ids must NOT appear in the in-clause
    assert "10" not in milvus_expr
    assert "20" not in milvus_expr
    # There must be no must_not clause (in-clause suffices)
    assert "not in" not in milvus_expr

    es_filter = es_kwargs["filter"]
    assert len(es_filter) == 1
    terms_clause = es_filter[0]
    assert terms_clause == {"terms": {"metadata.document_id": [5]}}


@pytest.mark.asyncio
async def test_specific_files_all_non_primary():
    """Branch B: target [10, 20], excluded [10, 20] -> both retrievers skipped (None, None)."""
    svc = _make_service()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[10, 20])

    milvus_kwargs, es_kwargs = await svc._build_folder_search_kwargs(
        knowledge_id=1,
        target_file_ids=[10, 20],
    )

    # Caller must detect None and skip retriever construction
    assert milvus_kwargs is None
    assert es_kwargs is None


@pytest.mark.asyncio
async def test_specific_files_empty_target():
    """Branch B: target [] (empty list after tag intersection), excluded irrelevant -> (None, None)."""
    svc = _make_service()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[])

    milvus_kwargs, es_kwargs = await svc._build_folder_search_kwargs(
        knowledge_id=1,
        target_file_ids=[],
    )

    # Empty candidate set -> no retrievers regardless of exclusion list
    assert milvus_kwargs is None
    assert es_kwargs is None

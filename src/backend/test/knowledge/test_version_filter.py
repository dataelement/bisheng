"""Tests for the version_filter RAG helper module."""
import pytest

from bisheng.knowledge.rag.version_filter import build_primary_only_filter


def test_empty_ids_no_base():
    """Empty excluded_file_ids with no base inputs -> (None, [])."""
    milvus_expr, es_filter = build_primary_only_filter([])
    assert milvus_expr is None
    assert es_filter == []


def test_empty_ids_with_base_inputs():
    """Empty excluded_file_ids with base inputs -> returns base inputs unchanged."""
    base_expr = "document_id in [5, 10, 30]"
    base_es = [{"term": {"metadata.foo": 1}}]

    milvus_expr, es_filter = build_primary_only_filter(
        [],
        base_milvus_expr=base_expr,
        base_es_filter=base_es,
    )
    assert milvus_expr == base_expr
    assert es_filter == base_es


def test_exclude_ids_no_base():
    """Exclude [10, 20] with no base -> correct Milvus clause and ES filter."""
    milvus_expr, es_filter = build_primary_only_filter([10, 20])
    assert milvus_expr == "document_id not in [10, 20]"
    assert es_filter == [{"bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}}]


def test_exclude_ids_with_both_bases():
    """Exclude [10, 20] with both bases -> Milvus joined by ' and '; ES appended."""
    base_expr = "document_id in [5, 10, 30]"
    base_es = [{"term": {"metadata.foo": 1}}]

    milvus_expr, es_filter = build_primary_only_filter(
        [10, 20],
        base_milvus_expr=base_expr,
        base_es_filter=base_es,
    )

    # Both clauses present joined with " and "
    assert "document_id not in [10, 20]" in milvus_expr
    assert base_expr in milvus_expr
    assert " and " in milvus_expr

    # ES filter contains the original term AND the new must_not block
    assert {"term": {"metadata.foo": 1}} in es_filter
    assert {"bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}} in es_filter
    assert len(es_filter) == 2


def test_single_element_list():
    """Single-element list [42] -> Milvus uses array literal [42], ES uses [42]."""
    milvus_expr, es_filter = build_primary_only_filter([42])
    assert milvus_expr == "document_id not in [42]"
    assert es_filter == [{"bool": {"must_not": {"terms": {"metadata.document_id": [42]}}}}]


def test_base_es_filter_immutability():
    """Passing a non-empty base_es_filter must NOT mutate the original list."""
    original = [{"term": {"metadata.foo": 1}}]
    original_copy = list(original)

    build_primary_only_filter([10, 20], base_es_filter=original)

    # The caller's list must remain unchanged
    assert original == original_copy
    assert len(original) == 1

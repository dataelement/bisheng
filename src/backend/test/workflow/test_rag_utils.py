"""Tests for RagUtils.init_knowledge_retriever primary-version-only filter injection.

Strategy A: narrow unit tests — construct a minimal RagUtils-like object (bypassing
BaseNode machinery) with hand-set attributes, mock dependencies, and assert the
search_kwargs passed to MultiRetriever contain the expected Milvus expr / ES filter.

Strategy B: worker async-loop wrapper smoke test for _fetch_non_primary_file_ids.
"""
from __future__ import annotations

import sys
import types
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from bisheng.knowledge.rag.version_filter import build_primary_only_filter
from bisheng.workflow.common.knowledge import ConditionCases, RagUtils


# ---------------------------------------------------------------------------
# Helpers — build a minimal RagUtils without full BaseNode init
# ---------------------------------------------------------------------------

def _make_rag_utils(
    knowledge_vector_list: Dict,
    metadata_filter: Optional[ConditionCases] = None,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> RagUtils:
    """Construct a RagUtils instance without triggering BaseNode.__init__."""
    # Bypass __init__ entirely
    obj = object.__new__(RagUtils)
    obj._knowledge_vector_list = knowledge_vector_list
    obj._metadata_filter = metadata_filter or ConditionCases(enabled=False)
    obj._keyword_weight = keyword_weight
    obj._vector_weight = vector_weight
    obj._retriever_kwargs = {"k": 100, "param": {"ef": 110}}
    obj._multi_milvus_retriever = None
    obj._multi_es_retriever = None
    return obj


def _make_knowledge_info(
    knowledge_id: int,
    with_milvus: bool = True,
    with_es: bool = True,
):
    """Return a knowledge_info dict with mock vector stores."""
    knowledge = MagicMock()
    knowledge.id = knowledge_id
    knowledge.metadata_fields = []
    info = {"knowledge": knowledge}
    if with_milvus:
        info["milvus"] = MagicMock(name=f"milvus_{knowledge_id}")
    if with_es:
        info["es"] = MagicMock(name=f"es_{knowledge_id}")
    return info


def _install_fake_worker_asyncio_utils(monkeypatch, run_async_task):
    import bisheng

    worker_mod = types.ModuleType("bisheng.worker")
    worker_mod.__path__ = []
    asyncio_utils_mod = types.ModuleType("bisheng.worker._asyncio_utils")
    asyncio_utils_mod.run_async_task = run_async_task
    worker_mod._asyncio_utils = asyncio_utils_mod

    monkeypatch.setattr(bisheng, "worker", worker_mod, raising=False)
    monkeypatch.setitem(sys.modules, "bisheng.worker", worker_mod)
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", asyncio_utils_mod)


# ---------------------------------------------------------------------------
# Strategy A — unit tests with mocked _fetch_non_primary_file_ids
# ---------------------------------------------------------------------------

class TestInitKnowledgeRetrieverNoExclusions:
    """Test case 1: no non-primary exclusions."""

    def test_milvus_expr_unchanged_when_no_exclusions(self):
        """With no excluded ids, the milvus expr must match the original metadata filter."""
        knowledge_id = 1
        knowledge_vector_list = {knowledge_id: _make_knowledge_info(knowledge_id)}

        # Metadata filter returns a file-id in-clause
        metadata_filter = MagicMock(spec=ConditionCases)
        metadata_filter.get_knowledge_filter.return_value = (
            "document_id in [5, 6]",
            {"filter": [{"terms": {"metadata.document_id": [5, 6]}}]},
        )

        obj = _make_rag_utils(knowledge_vector_list, metadata_filter=metadata_filter)

        captured_milvus_kwargs = []
        captured_es_kwargs = []

        def _fake_multi_retriever(vectors, search_kwargs, finally_k):
            # Capture the search_kwargs that would be passed to MultiRetriever
            if vectors and hasattr(vectors[0], "_mock_name") and "milvus" in str(vectors[0]._mock_name):
                captured_milvus_kwargs.extend(search_kwargs)
            else:
                captured_es_kwargs.extend(search_kwargs)
            m = MagicMock()
            return m

        with patch.object(obj, "_fetch_non_primary_file_ids", return_value=[]):
            with patch(
                "bisheng.workflow.common.knowledge.MultiRetriever",
                side_effect=_fake_multi_retriever,
            ):
                obj.init_knowledge_retriever()

        # Should have one entry each for milvus and es
        assert len(captured_milvus_kwargs) == 1
        assert len(captured_es_kwargs) == 1

        # Milvus: expr must equal original, k/param preserved
        milvus_kw = captured_milvus_kwargs[0]
        assert milvus_kw["expr"] == "document_id in [5, 6]"
        assert milvus_kw["k"] == 100
        assert milvus_kw["param"] == {"ef": 110}

        # ES: filter list unchanged, k/param preserved
        es_kw = captured_es_kwargs[0]
        assert es_kw["filter"] == [{"terms": {"metadata.document_id": [5, 6]}}]
        assert es_kw["k"] == 100

    def test_no_expr_and_no_filter_key_when_no_exclusions_and_no_metadata_filter(self):
        """No metadata filter + no exclusions: expr absent, filter key absent."""
        knowledge_id = 1
        knowledge_vector_list = {knowledge_id: _make_knowledge_info(knowledge_id)}

        # Metadata filter disabled → returns "", {}
        metadata_filter = MagicMock(spec=ConditionCases)
        metadata_filter.get_knowledge_filter.return_value = ("", {})

        obj = _make_rag_utils(knowledge_vector_list, metadata_filter=metadata_filter)

        captured_milvus_kwargs = []
        captured_es_kwargs = []

        def _fake_multi_retriever(vectors, search_kwargs, finally_k):
            if vectors and hasattr(vectors[0], "_mock_name") and "milvus" in str(vectors[0]._mock_name):
                captured_milvus_kwargs.extend(search_kwargs)
            else:
                captured_es_kwargs.extend(search_kwargs)
            return MagicMock()

        with patch.object(obj, "_fetch_non_primary_file_ids", return_value=[]):
            with patch(
                "bisheng.workflow.common.knowledge.MultiRetriever",
                side_effect=_fake_multi_retriever,
            ):
                obj.init_knowledge_retriever()

        assert len(captured_milvus_kwargs) == 1
        assert len(captured_es_kwargs) == 1

        # No expr key when there is nothing to filter
        assert "expr" not in captured_milvus_kwargs[0]

        # No filter key when no filter list
        assert "filter" not in captured_es_kwargs[0]


class TestInitKnowledgeRetrieverWithExclusions:
    """Test case 2: non-primary exclusions [10, 20]."""

    def _run_with_exclusions(
        self,
        base_milvus_str: str,
        base_es_filter_dict: dict,
        excluded: List[int],
    ):
        """Helper: wire up a single knowledge and capture search_kwargs."""
        knowledge_id = 1
        knowledge_vector_list = {knowledge_id: _make_knowledge_info(knowledge_id)}

        metadata_filter = MagicMock(spec=ConditionCases)
        metadata_filter.get_knowledge_filter.return_value = (
            base_milvus_str,
            base_es_filter_dict,
        )

        obj = _make_rag_utils(knowledge_vector_list, metadata_filter=metadata_filter)

        captured_milvus_kwargs = []
        captured_es_kwargs = []

        def _fake_multi_retriever(vectors, search_kwargs, finally_k):
            if vectors and hasattr(vectors[0], "_mock_name") and "milvus" in str(vectors[0]._mock_name):
                captured_milvus_kwargs.extend(search_kwargs)
            else:
                captured_es_kwargs.extend(search_kwargs)
            return MagicMock()

        with patch.object(obj, "_fetch_non_primary_file_ids", return_value=excluded):
            with patch(
                "bisheng.workflow.common.knowledge.MultiRetriever",
                side_effect=_fake_multi_retriever,
            ):
                obj.init_knowledge_retriever()

        return captured_milvus_kwargs, captured_es_kwargs

    def test_with_metadata_filter_and_exclusions(self):
        """Milvus expr AND-combines base filter with not-in; ES filter appends must_not."""
        milvus_kws, es_kws = self._run_with_exclusions(
            base_milvus_str="document_id in [5, 6]",
            base_es_filter_dict={"filter": [{"terms": {"metadata.document_id": [5, 6]}}]},
            excluded=[10, 20],
        )

        assert len(milvus_kws) == 1
        assert len(es_kws) == 1

        milvus_expr = milvus_kws[0]["expr"]
        # Both clauses must be present
        assert "document_id in [5, 6]" in milvus_expr
        assert "document_id not in [10, 20]" in milvus_expr
        # Milvus uses lowercase "and" to combine
        assert " and " in milvus_expr

        es_filter = es_kws[0]["filter"]
        # Original terms clause still present
        assert {"terms": {"metadata.document_id": [5, 6]}} in es_filter
        # must_not clause appended
        assert {
            "bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}
        } in es_filter

    def test_no_metadata_filter_with_exclusions(self):
        """No metadata filter + exclusions: Milvus expr is just not-in; ES has only must_not."""
        milvus_kws, es_kws = self._run_with_exclusions(
            base_milvus_str="",
            base_es_filter_dict={},
            excluded=[10, 20],
        )

        assert len(milvus_kws) == 1
        assert len(es_kws) == 1

        milvus_expr = milvus_kws[0]["expr"]
        assert milvus_expr == "document_id not in [10, 20]"

        es_filter = es_kws[0]["filter"]
        assert len(es_filter) == 1
        assert es_filter[0] == {
            "bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}
        }

    def test_ids_are_sorted_in_output(self):
        """Exclusion ids must be sorted ascending in Milvus literal and ES list."""
        milvus_kws, es_kws = self._run_with_exclusions(
            base_milvus_str="",
            base_es_filter_dict={},
            excluded=[20, 10],  # intentionally unsorted
        )
        milvus_expr = milvus_kws[0]["expr"]
        assert "not in [10, 20]" in milvus_expr

        es_filter = es_kws[0]["filter"]
        must_not_ids = es_filter[0]["bool"]["must_not"]["terms"]["metadata.document_id"]
        assert must_not_ids == [10, 20]


class TestInitKnowledgeRetrieverSkipsNoneFilter:
    """Test case 4: get_knowledge_filter returns (None, None) — knowledge skipped."""

    def test_knowledge_skipped_when_no_files_match_filter(self):
        """When get_knowledge_filter returns (None, None), that knowledge is excluded."""
        knowledge_id = 1
        knowledge_vector_list = {knowledge_id: _make_knowledge_info(knowledge_id)}

        metadata_filter = MagicMock(spec=ConditionCases)
        metadata_filter.get_knowledge_filter.return_value = (None, None)

        obj = _make_rag_utils(knowledge_vector_list, metadata_filter=metadata_filter)

        multi_retriever_calls = []

        def _fake_multi_retriever(vectors, search_kwargs, finally_k):
            multi_retriever_calls.append((vectors, search_kwargs))
            return MagicMock()

        with patch.object(obj, "_fetch_non_primary_file_ids", return_value=[10]) as mock_fetch:
            with patch(
                "bisheng.workflow.common.knowledge.MultiRetriever",
                side_effect=_fake_multi_retriever,
            ):
                obj.init_knowledge_retriever()

        # MultiRetriever must not be called (no vectors to retrieve from)
        assert len(multi_retriever_calls) == 0
        # _fetch_non_primary_file_ids still called (we fetch before the loop)
        mock_fetch.assert_called_once_with([knowledge_id])


class TestInitKnowledgeRetrieverEmptyList:
    """Test case 4b: empty _knowledge_vector_list — MultiRetriever not constructed."""

    def test_empty_knowledge_vector_list_no_retriever(self):
        """Empty knowledge list produces no MultiRetriever instances.

        The guard `if not self._knowledge_vector_list` is True for {}, so the reload
        branch fires.  We mock get_multi_knowledge_vectorstore_sync to return {} and
        add the minimal node attributes that the reload call signature needs.
        """
        obj = _make_rag_utils(knowledge_vector_list={})
        # Add attrs required by the reload branch inside init_knowledge_retriever
        obj.user_id = "test-user"
        obj._knowledge_value = []
        obj.user_info = MagicMock()
        obj.user_info.user_name = "tester"
        obj._knowledge_auth = False

        multi_retriever_calls = []

        def _fake_multi_retriever(vectors, search_kwargs, finally_k):
            multi_retriever_calls.append((vectors, search_kwargs))
            return MagicMock()

        with patch.object(obj, "_fetch_non_primary_file_ids", return_value=[]) as mock_fetch:
            with patch(
                "bisheng.workflow.common.knowledge.MultiRetriever",
                side_effect=_fake_multi_retriever,
            ):
                with patch(
                    "bisheng.workflow.common.knowledge.KnowledgeRag"
                    ".get_multi_knowledge_vectorstore_sync",
                    return_value={},
                ):
                    obj.init_knowledge_retriever()

        # _fetch called with [] (empty knowledge_ids from the {} return value)
        mock_fetch.assert_called_once_with([])
        assert len(multi_retriever_calls) == 0
        assert obj._multi_milvus_retriever is None
        assert obj._multi_es_retriever is None


# ---------------------------------------------------------------------------
# Strategy B — worker async-loop wrapper smoke test
# ---------------------------------------------------------------------------

class TestFetchNonPrimaryFileIds:
    """Smoke test: _fetch_non_primary_file_ids handles empty list gracefully."""

    def test_empty_knowledge_ids_returns_empty(self):
        """Empty input short-circuits before any DB call."""
        obj = _make_rag_utils(knowledge_vector_list={})
        result = obj._fetch_non_primary_file_ids([])
        assert result == []

    def test_uses_worker_async_loop_runner(self, monkeypatch):
        """Celery workflow code must not create a temporary asyncio.run loop."""
        obj = _make_rag_utils(knowledge_vector_list={})

        def _fake_run_async_task(coro_factory):
            assert callable(coro_factory)
            return [10, 20]

        _install_fake_worker_asyncio_utils(monkeypatch, _fake_run_async_task)

        with patch("asyncio.run", side_effect=AssertionError("asyncio.run must not be used")):
            result = obj._fetch_non_primary_file_ids([1, 2, 3])
        assert result == [10, 20]

    def test_exception_returns_empty(self, monkeypatch):
        """Any worker async-loop runner exception returns [] as a best-effort fallback."""
        obj = _make_rag_utils(knowledge_vector_list={})

        def _raise(_coro_factory):
            raise Exception("simulated DB failure")

        _install_fake_worker_asyncio_utils(monkeypatch, _raise)

        result = obj._fetch_non_primary_file_ids([1, 2, 3])
        assert result == []

    def test_runtime_error_returns_empty(self, monkeypatch):
        """RuntimeError (already-running event loop) returns [] gracefully."""
        obj = _make_rag_utils(knowledge_vector_list={})

        def _raise(_coro_factory):
            raise RuntimeError("event loop already running")

        _install_fake_worker_asyncio_utils(monkeypatch, _raise)

        result = obj._fetch_non_primary_file_ids([1, 2, 3])
        assert result == []


# ---------------------------------------------------------------------------
# Integration: verify build_primary_only_filter is used (not mocked)
# ---------------------------------------------------------------------------

class TestBuildPrimaryOnlyFilterDirect:
    """Directly verify build_primary_only_filter output shapes used in production."""

    def test_no_exclusions_unchanged(self):
        milvus_expr, es_filter = build_primary_only_filter(
            [],
            base_milvus_expr="document_id in [1, 2]",
            base_es_filter=[{"terms": {"metadata.document_id": [1, 2]}}],
        )
        assert milvus_expr == "document_id in [1, 2]"
        assert es_filter == [{"terms": {"metadata.document_id": [1, 2]}}]

    def test_with_exclusions_combined(self):
        milvus_expr, es_filter = build_primary_only_filter(
            [10, 20],
            base_milvus_expr="document_id in [1, 2]",
            base_es_filter=[{"terms": {"metadata.document_id": [1, 2]}}],
        )
        assert milvus_expr == "document_id in [1, 2] and document_id not in [10, 20]"
        assert {"bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}} in es_filter
        assert {"terms": {"metadata.document_id": [1, 2]}} in es_filter

    def test_no_base_with_exclusions(self):
        milvus_expr, es_filter = build_primary_only_filter([10, 20])
        assert milvus_expr == "document_id not in [10, 20]"
        assert len(es_filter) == 1
        assert es_filter[0] == {
            "bool": {"must_not": {"terms": {"metadata.document_id": [10, 20]}}}
        }

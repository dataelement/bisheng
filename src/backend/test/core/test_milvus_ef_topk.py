"""Regression tests for the HNSW ``ef < k`` search failure.

Milvus HNSW search requires the expansion factor ``ef`` to be >= the requested
topK (``k``); otherwise the QueryNode rejects the search with
``ef(110) should be larger than k(300)``. Callers may legitimately request a
larger ``k`` than the fixed ``ef`` baked into their search params -- e.g. the
knowledge-space permission-filter recall loop scales ``k`` by a multiplier
(100 * 3 = 300) while leaving ``ef`` hard-coded at 110. The wrapper must raise
``ef`` to cover ``k`` transparently so no caller can trip this constraint.
"""

from __future__ import annotations

import asyncio

from langchain_milvus import Milvus as _LangchainMilvus

from bisheng.core.vectorstore.milvus import Milvus

# --- pure helper: ef >= k coverage -----------------------------------------


def test_flat_ef_below_k_is_bumped_to_k():
    param = {"ef": 110, "metric_type": "L2"}

    result = Milvus._ensure_ef_covers_k(param, 300)

    assert result["ef"] == 300
    assert result["metric_type"] == "L2"


def test_flat_ef_at_or_above_k_is_unchanged():
    param = {"ef": 500, "metric_type": "L2"}

    result = Milvus._ensure_ef_covers_k(param, 300)

    assert result["ef"] == 500


def test_nested_ef_below_k_is_bumped_to_k():
    param = {"metric_type": "L2", "params": {"ef": 110}}

    result = Milvus._ensure_ef_covers_k(param, 300)

    assert result["params"]["ef"] == 300
    assert result["metric_type"] == "L2"


def test_nested_ef_at_or_above_k_is_unchanged():
    param = {"metric_type": "L2", "params": {"ef": 400}}

    result = Milvus._ensure_ef_covers_k(param, 300)

    assert result["params"]["ef"] == 400


def test_does_not_mutate_input_param():
    param = {"ef": 110}

    Milvus._ensure_ef_covers_k(param, 300)

    assert param["ef"] == 110  # original untouched


def test_none_param_returns_none():
    assert Milvus._ensure_ef_covers_k(None, 300) is None


def test_param_without_ef_is_unchanged():
    param = {"metric_type": "L2"}

    result = Milvus._ensure_ef_covers_k(param, 300)

    assert result == {"metric_type": "L2"}


# --- override delegates corrected param to the parent ----------------------


def _make_store():
    store = object.__new__(Milvus)
    return store


def test_collection_search_passes_bumped_param_to_parent(monkeypatch):
    captured = {}

    def fake_parent(self, embedding_or_text, k=4, param=None, expr=None, timeout=None, **kwargs):
        captured["k"] = k
        captured["param"] = param
        return ["sentinel"]

    monkeypatch.setattr(_LangchainMilvus, "_collection_search", fake_parent)

    store = _make_store()
    out = store._collection_search([0.1, 0.2], k=300, param={"ef": 110})

    assert out == ["sentinel"]
    assert captured["k"] == 300
    assert captured["param"]["ef"] == 300


def test_acollection_search_passes_bumped_param_to_parent(monkeypatch):
    captured = {}

    async def fake_parent(self, embedding_or_text, k=4, param=None, expr=None, timeout=None, **kwargs):
        captured["k"] = k
        captured["param"] = param
        return ["sentinel"]

    monkeypatch.setattr(_LangchainMilvus, "_acollection_search", fake_parent)

    store = _make_store()
    out = asyncio.get_event_loop().run_until_complete(
        store._acollection_search([0.1, 0.2], k=300, param={"metric_type": "L2", "params": {"ef": 110}})
    )

    assert out == ["sentinel"]
    assert captured["k"] == 300
    assert captured["param"]["params"]["ef"] == 300

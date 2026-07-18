from __future__ import annotations

import pytest

from bisheng.core.vectorstore import milvus as milvus_module
from bisheng.core.vectorstore.milvus import Milvus


def _raise_no_index_params(self):
    raise ValueError("No index params provided. Could not determine relevance function.")


def test_milvus_relevance_score_falls_back_to_l2_without_index_params(monkeypatch):
    monkeypatch.setattr(
        milvus_module._LangchainMilvus,
        "_select_relevance_score_fn",
        _raise_no_index_params,
    )
    store = object.__new__(Milvus)
    store.index_params = None

    relevance = store._select_relevance_score_fn()

    assert relevance(0) == pytest.approx(1)
    assert relevance(4) == pytest.approx(0)


def test_milvus_relevance_score_respects_ip_index_params(monkeypatch):
    monkeypatch.setattr(
        milvus_module._LangchainMilvus,
        "_select_relevance_score_fn",
        _raise_no_index_params,
    )
    store = object.__new__(Milvus)
    store.index_params = {"metric_type": "IP"}

    relevance = store._select_relevance_score_fn()

    assert relevance(1) == pytest.approx(1)
    assert relevance(-1) == pytest.approx(0)


def test_milvus_relevance_score_reraises_other_value_errors(monkeypatch):
    def raise_other(self):
        raise ValueError("unsupported metric")

    monkeypatch.setattr(
        milvus_module._LangchainMilvus,
        "_select_relevance_score_fn",
        raise_other,
    )
    store = object.__new__(Milvus)
    store.index_params = None

    with pytest.raises(ValueError, match="unsupported metric"):
        store._select_relevance_score_fn()

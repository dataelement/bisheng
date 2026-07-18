"""Regression tests for the concurrent-metadata-loss bug.

When several files are uploaded concurrently to a *new* knowledge base, only the
worker that wins the schema-creation lock builds its `self.fields` snapshot from
the freshly-created collection. Every other worker constructed its Milvus
instance while the collection still did not exist, so its `self.fields` stayed
empty. langchain-milvus only re-extracts fields inside `_init`, which runs solely
when the collection is *absent* -- so once a peer creates the collection, the
waiting workers keep an empty `self.fields` and `_prepare_insert_list` silently
drops every metadata field (e.g. the non-nullable `document_id`), making the
insert fail and the file land in a terminal FAILED state.

The wrapper must self-heal: before inserting, if `self.fields` is empty but the
collection now exists, re-extract the fields from the live schema.
"""

from __future__ import annotations

from types import SimpleNamespace

from bisheng.core.vectorstore import milvus as milvus_module
from bisheng.core.vectorstore.milvus import Milvus


def _make_store(*, fields, collection_exists):
    store = object.__new__(Milvus)
    store.fields = list(fields)
    store.collection_name = "kb_99"
    # `client` is a read-only property backed by `_milvus_client`.
    store._milvus_client = SimpleNamespace(has_collection=lambda name: collection_exists)
    return store


def test_ensure_fields_loaded_reextracts_when_empty_and_collection_exists():
    store = _make_store(fields=[], collection_exists=True)

    def fake_extract():
        store.fields.extend(["pk", "text", "vector", "document_id", "knowledge_id"])

    store._extract_fields = fake_extract

    store._ensure_fields_loaded()

    assert "document_id" in store.fields


def test_ensure_fields_loaded_is_noop_when_fields_already_populated():
    populated = ["pk", "text", "vector", "document_id"]
    store = _make_store(fields=populated, collection_exists=True)
    calls = []
    store._extract_fields = lambda: calls.append(1)

    store._ensure_fields_loaded()

    assert calls == []
    assert store.fields == populated


def test_ensure_fields_loaded_is_noop_when_collection_missing():
    store = _make_store(fields=[], collection_exists=False)
    calls = []
    store._extract_fields = lambda: calls.append(1)

    store._ensure_fields_loaded()

    assert calls == []
    assert store.fields == []


def test_add_texts_reloads_empty_fields_before_insert(monkeypatch):
    observed = {}

    def fake_super_add_texts(self, texts, *args, **kwargs):
        observed["fields_at_insert"] = list(self.fields)
        return ["id1"]

    monkeypatch.setattr(milvus_module._LangchainMilvus, "add_texts", fake_super_add_texts)

    store = _make_store(fields=[], collection_exists=True)

    def fake_extract():
        store.fields.append("document_id")

    store._extract_fields = fake_extract

    store.add_texts(["hello"], metadatas=[{"document_id": 1}])

    assert "document_id" in observed["fields_at_insert"]

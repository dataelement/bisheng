"""T714: native IO shapes; no real Milvus/ES or model provider is contacted.

The production handler and existing KnowledgeRag entry points are exercised;
only native initialization/Collection/HTTP and future Owner guard are doubled.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from elastic_transport import ApiResponseMeta, NodeConfig, ObjectApiResponse
from elasticsearch import NotFoundError

from bisheng.common.errcode.knowledge import (
    KnowledgeFileFailedError,
    KnowledgeProcessingObsoleteError,
    ResourceReferenceInvalidError,
)
from bisheng.core.ai import FakeEmbeddings
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.worker.knowledge import metadata_worker as module


def response(body, status=200):
    return ObjectApiResponse(
        body=body,
        meta=ApiResponseMeta(
            status=status, http_version="1.1", headers={}, duration=0, node=NodeConfig("http", "offline", 9200)
        ),
    )


def record(number, file_id=81):
    return {
        "pk": number,
        "vector": [0.25, number / 100000],
        "text": f"human-edited-{number}",
        "document_id": file_id,
        "knowledge_id": 40,
        "extra": {"kept": [number]},
        "user_metadata": {
            "old": "old-chunk-value",
            "alias": "stale-alias",
            "fresh": "stale-deleted-value",
            "kept": f"chunk-specific-{number}",
        },
    }


class NativeIterator:
    def __init__(self, records, events):
        self.records, self.events, self.offset, self.closed = deepcopy(records), events, 0, False
        self.reads, self.fail_at, self.close_error = 0, None, None

    def next(self):
        self.events.append("next")
        self.reads += 1
        if self.fail_at == self.reads:
            raise RuntimeError("native iterator interrupted")
        page = self.records[self.offset : self.offset + 1000]
        self.offset += len(page)
        return deepcopy(page)

    def close(self):
        self.events.append("close")
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class NativeCollection:
    def __init__(self, records, events):
        self.records = {row["pk"]: deepcopy(row) for row in records}
        self.events, self.batches, self.iterators = events, [], []
        self.upsert_error, self.upsert_count = None, None
        self.schema = SimpleNamespace(fields=[SimpleNamespace(name=name) for name in record(1)])
        self.iterator_options = {}

    def query_iterator(self, *, batch_size, limit, expr, output_fields):
        self.events.append("iterator")
        assert batch_size == 1000 and limit == -1 and expr == "document_id == 81"
        assert output_fields == [field.name for field in self.schema.fields]
        iterator = NativeIterator([row for row in self.records.values() if row["document_id"] == 81], self.events)
        for key, value in self.iterator_options.items():
            setattr(iterator, key, value)
        self.iterators.append(iterator)
        return iterator

    def upsert(self, data):
        self.events.append("upsert")
        if self.upsert_error is not None:
            raise self.upsert_error
        self.batches.append(deepcopy(data))
        self.records.update({row["pk"]: deepcopy(row) for row in data})
        return SimpleNamespace(upsert_count=len(data) if self.upsert_count is None else self.upsert_count)


@pytest.fixture
def native(monkeypatch):
    events = []
    rows = [record(1), record(2), record(999, 82)]
    collection = NativeCollection(rows, events)
    state = SimpleNamespace(
        events=events, collection=collection, es_rows=deepcopy(rows), es_error=None, es_result=None, calls=[], deny=None
    )
    knowledge = Knowledge(
        id=40,
        tenant_id=101,
        user_id=7,
        name="metadata",
        type=3,
        model="11",
        index_name="index-40",
        collection_name="collection-40",
        model_config_revision=4,
        index_generation="g4",
    )
    state.knowledge = knowledge

    async def vector_init(*args, **kwargs):
        events.append("vector_init")
        assert args == (7,) and kwargs["knowledge"] is knowledge
        assert isinstance(kwargs["embeddings"], FakeEmbeddings)
        assert kwargs["expected_model_config_revision"] == 4 and kwargs["expected_index_generation"] == "g4"
        return SimpleNamespace(col=collection)

    async def es_init(*, knowledge, **kwargs):
        events.append("es_init")
        assert knowledge is state.knowledge
        assert kwargs["expected_model_config_revision"] == 4 and kwargs["expected_index_generation"] == "g4"
        return SimpleNamespace(client=SimpleNamespace(update_by_query=state.update))

    async def update(*, index, body, refresh):
        events.append("es")
        assert index == "index-40" and refresh is True
        assert body["query"] == {"term": {"metadata.document_id": 81}}
        state.calls.append(deepcopy(body))
        if state.es_error is not None:
            raise state.es_error
        params = body["script"]["params"]
        assert "params.affected_fields" in body["script"]["source"]
        assert "params.replacements" in body["script"]["source"]
        matched = [row for row in state.es_rows if row["document_id"] == 81]
        for row in matched:
            current = deepcopy(row.get("user_metadata")) or {}
            for field in params["affected_fields"]:
                current.pop(field, None)
            current.update(deepcopy(params["replacements"]))
            row["user_metadata"] = current
        body = {
            "timed_out": False,
            "failures": [],
            "version_conflicts": 0,
            "total": len(matched),
            "updated": len(matched),
            "deleted": 0,
            "noops": 0,
        }
        return response(state.es_result if state.es_result is not None else body)

    async def guard():
        events.append("guard")
        if state.deny is not None:
            state.deny()

    state.update, state.guard = AsyncMock(side_effect=update), guard
    state.vector_init, state.es_init = AsyncMock(side_effect=vector_init), AsyncMock(side_effect=es_init)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", state.vector_init)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", state.es_init)
    state.embed_documents, state.embed_query = (
        Mock(side_effect=AssertionError("embedding forbidden")),
        Mock(side_effect=AssertionError("embedding forbidden")),
    )
    monkeypatch.setattr(FakeEmbeddings, "embed_documents", state.embed_documents)
    monkeypatch.setattr(FakeEmbeddings, "embed_query", state.embed_query)
    return state


async def apply(native, **overrides):
    values = {
        "alias": {"field_value": "frozen-renamed-value", "field_type": "string", "updated_at": 100},
        "kept": {"field_value": "file-level-value-must-not-overwrite-chunks"},
    }
    kwargs = {
        "knowledge": native.knowledge,
        "invoke_user_id": 7,
        "file_id": 81,
        "affected_fields": ("old", "alias", "fresh"),
        "after_values": values,
        "guard": native.guard,
    }
    kwargs.update(overrides)
    return await module.apply_metadata_index_item(**kwargs)


async def test_10001_records_preserve_native_vectors_text_and_non_target_fields(native):
    rows = [record(number) for number in range(1, 10002)] + [record(20000, 82)]
    native.collection.records = {row["pk"]: deepcopy(row) for row in rows}
    native.es_rows = deepcopy(rows)
    outcome = await apply(native)
    assert (outcome.file_id, outcome.milvus_count, outcome.es_count) == (81, 10001, 10001)
    assert [len(batch) for batch in native.collection.batches] == [1000] * 10 + [1]
    assert native.collection.iterators[0].closed
    for original in rows:
        changed = native.collection.records[original["pk"]]
        assert {key: value for key, value in changed.items() if key != "user_metadata"} == {
            key: value for key, value in original.items() if key != "user_metadata"
        }
        if original["document_id"] == 81:
            assert changed["user_metadata"] == {
                "alias": "frozen-renamed-value",
                "kept": original["user_metadata"]["kept"],
            }
        else:
            assert changed == original
    assert native.collection.records[20000] == rows[-1] and native.es_rows[-1] == rows[-1]
    native.embed_documents.assert_not_called()
    native.embed_query.assert_not_called()
    with pytest.raises(FrozenInstanceError):
        outcome.es_count = 0


async def test_guards_precede_every_controlled_io_and_final_return(native):
    await apply(native)
    for index, event in enumerate(native.events):
        if event in {"vector_init", "es_init", "iterator", "next", "upsert", "es"}:
            assert native.events[index - 1] == "guard"
    assert native.events[-1] == "guard"


async def test_same_frozen_snapshot_recovers_es_failure_without_losing_renamed_values(native):
    error = RuntimeError("ES offline")
    native.es_error = error
    with pytest.raises(KnowledgeFileFailedError) as failure:
        await apply(native)
    assert failure.value.__cause__ is error
    assert native.collection.records[1]["user_metadata"]["alias"] == "frozen-renamed-value"
    native.es_error = None
    await apply(native)
    before = deepcopy(native.collection.records)
    await apply(native)
    assert native.collection.records == before
    assert native.es_rows[0]["user_metadata"] == native.collection.records[1]["user_metadata"]


@pytest.mark.parametrize(
    "result",
    [
        {"timed_out": True, "failures": [], "version_conflicts": 0, "total": 2, "updated": 2, "deleted": 0, "noops": 0},
        {
            "timed_out": False,
            "failures": [{"cause": "failed"}],
            "version_conflicts": 0,
            "total": 2,
            "updated": 2,
            "deleted": 0,
            "noops": 0,
        },
        {
            "timed_out": False,
            "failures": [],
            "version_conflicts": 1,
            "total": 2,
            "updated": 1,
            "deleted": 0,
            "noops": 0,
        },
        {
            "timed_out": False,
            "failures": [],
            "version_conflicts": 0,
            "total": 2,
            "updated": 1,
            "deleted": 0,
            "noops": 0,
        },
        {
            "timed_out": False,
            "failures": [],
            "version_conflicts": 0,
            "total": 2,
            "updated": True,
            "deleted": 0,
            "noops": 1,
        },
        {"timed_out": False, "failures": [], "version_conflicts": 0, "total": 2, "updated": 2, "deleted": 0},
    ],
)
async def test_native_es_partial_or_incomplete_statistics_are_failures(native, result):
    native.es_result = result
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.collection.iterators[0].closed


@pytest.mark.parametrize("bad_count", [0, 1, True, None])
async def test_native_upsert_count_must_match_the_actual_batch(native, bad_count):
    if bad_count is None:
        native.collection.upsert = lambda data: SimpleNamespace()
    else:
        native.collection.upsert_count = bad_count
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.collection.iterators[0].closed and not native.calls


async def test_native_iterator_error_closes_and_stops_before_es(native):
    native.collection.iterator_options["fail_at"] = 1
    with pytest.raises(KnowledgeFileFailedError) as failure:
        await apply(native)
    assert isinstance(failure.value.__cause__, RuntimeError)
    assert native.collection.iterators[0].closed and not native.calls and not native.collection.batches


@pytest.mark.parametrize("field", ["pk", "vector", "text"])
async def test_partial_native_records_cannot_lose_primary_vector_or_chunk_text(native, field):
    native.collection.records[1].pop(field)
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.collection.iterators[0].closed and not native.calls and not native.collection.batches


async def test_missing_physical_collection_cannot_be_reported_as_zero_success(native):
    native.vector_init.side_effect = None
    native.vector_init.return_value = SimpleNamespace(col=None)
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    native.es_init.assert_not_awaited()


async def test_primary_native_error_is_preserved_when_iterator_cleanup_also_fails(native):
    original = RuntimeError("primary-upsert-failure")
    native.collection.upsert_error = original
    native.collection.iterator_options["close_error"] = RuntimeError("cleanup failed")
    with pytest.raises(KnowledgeFileFailedError) as failure:
        await apply(native)
    assert failure.value.__cause__ is original
    assert native.collection.iterators[0].closed


@pytest.mark.parametrize("stage", ["initial", "after_batch", "after_es"])
async def test_owner_guard_rejection_stops_new_io_without_laundering_error(native, stage):
    original = KnowledgeProcessingObsoleteError()

    def deny():
        if (
            stage == "initial"
            or (stage == "after_batch" and native.collection.batches)
            or (stage == "after_es" and native.calls)
        ):
            raise original

    native.deny = deny
    with pytest.raises(KnowledgeProcessingObsoleteError) as failure:
        await apply(native)
    assert failure.value is original
    if stage == "initial":
        native.vector_init.assert_not_awaited()
    elif stage == "after_batch":
        assert native.collection.iterators[0].closed and not native.calls
        assert native.collection.iterators[0].reads == 1


@pytest.mark.parametrize("guard", [None, lambda: None])
async def test_real_awaitable_guard_is_mandatory_before_native_io(native, guard):
    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native, guard=guard)
    native.vector_init.assert_not_awaited()


@pytest.mark.parametrize("verdict", [False, True])
async def test_guard_cannot_silently_return_a_boolean_permission_decision(native, verdict):
    async def guard():
        return verdict

    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native, guard=guard)
    native.vector_init.assert_not_awaited()


async def test_real_zero_record_counts_are_allowed_but_missing_index_is_not(native):
    native.collection.records, native.es_rows = {}, []
    outcome = await apply(native)
    assert (outcome.milvus_count, outcome.es_count) == (0, 0)
    missing = NotFoundError(
        "missing",
        meta=ApiResponseMeta(
            status=404, http_version="1.1", headers={}, duration=0, node=NodeConfig("http", "offline", 9200)
        ),
        body={"error": "index_not_found_exception"},
    )
    native.es_error = missing
    with pytest.raises(KnowledgeFileFailedError) as failure:
        await apply(native)
    assert failure.value.__cause__ is missing


async def test_parameterized_field_names_and_values_do_not_enter_script_source(native):
    field = "old'field"
    await apply(native, affected_fields=(field,), after_values={field: {"field_value": "literal-secret-value"}})
    script = native.calls[-1]["script"]
    assert field not in script["source"] and "literal-secret-value" not in script["source"]
    assert script["params"]["replacements"] == {field: "literal-secret-value"}

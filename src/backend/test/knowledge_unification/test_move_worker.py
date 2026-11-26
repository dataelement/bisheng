"""T785: actual move-index adapter with only native/model transports isolated.

This is the index port for the later real Move Owner/J1 assembly. It does not
pretend to accept a business move, change ownership or complete a SQL item.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from elasticsearch import NotFoundError

from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, ResourceReferenceInvalidError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.ai import FakeEmbeddings
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.worker.knowledge import move_worker as module
from test.knowledge_unification.test_metadata_index_worker import response


def chunk(number, file_id=81):
    return {
        "_id": f"source-{number}",
        "_source": {
            "text": f"manual {number} ![image](/bucket/knowledge/images/40/{file_id}/same.png)",
            "metadata": {
                "document_id": file_id,
                "knowledge_id": 40,
                "chunk_index": number % 2,
                "document_name": "manual-title",
                "system": {"unchanged": [number]},
                "user_metadata": {"keep": f"chunk-value-{number}", "drop": "confirmed-loss", "system_key": "kept"},
            },
        },
    }


class NativeIterator:
    def __init__(self, rows, events):
        self.rows, self.events, self.offset, self.closed = deepcopy(rows), events, 0, False

    def next(self):
        self.events.append("mv_next")
        rows = self.rows[self.offset : self.offset + 1000]
        self.offset += len(rows)
        return deepcopy(rows)

    def close(self):
        self.closed = True


class NativeCollection:
    def __init__(self, events):
        self.rows, self.events, self.iterators, self.batches = [], events, [], []
        self.delete_error, self.delete_retains, self.insert_count, self.tamper = None, False, None, None
        self.schema = SimpleNamespace(
            fields=[
                SimpleNamespace(name=name, params={"dim": 2} if name == "vector" else {})
                for name in (
                    "pk",
                    "vector",
                    "text",
                    "knowledge_id",
                    "document_id",
                    "chunk_index",
                    "document_name",
                    "user_metadata",
                )
            ]
        )

    def delete(self, expr):
        self.events.append("mv_delete")
        assert expr == "document_id == 81"
        if self.delete_error:
            raise self.delete_error
        if not self.delete_retains:
            self.rows = [row for row in self.rows if row["document_id"] != 81]
        return SimpleNamespace(delete_count=1)

    def insert(self, data):
        self.events.append("mv_insert")
        self.batches.append(deepcopy(data))
        for row in data:
            assert "pk" not in row
            value = {**deepcopy(row), "pk": len(self.rows) + 1}
            if self.tamper:
                value = self.tamper(value)
            self.rows.append(value)
        return SimpleNamespace(
            insert_count=len(data) if self.insert_count is None else self.insert_count,
            primary_keys=list(range(len(data))),
        )

    def flush(self):
        self.events.append("mv_flush")

    def query_iterator(self, *, batch_size, limit, expr, output_fields):
        self.events.append("mv_iterator")
        assert batch_size == 1000 and limit == -1 and expr == "document_id == 81"
        assert output_fields == [field.name for field in self.schema.fields]
        iterator = NativeIterator([row for row in self.rows if row["document_id"] == 81], self.events)
        self.iterators.append(iterator)
        return iterator


class NativeES:
    def __init__(self, name, rows, events):
        self.name, self.rows, self.events = name, deepcopy(rows), events
        self.cursors, self.closed, self.cleared, self.pages = {}, False, [], []
        self.exists, self.fail_delete, self.fail_add, self.retains, self.tamper = True, None, None, False, None
        self.delete_result, self.add_ids = None, []
        self.total_override = None
        self.indices = SimpleNamespace(exists=self.index_exists, refresh=self.refresh)
        self.client = self

    async def index_exists(self, *, index):
        self.events.append(f"{self.name}_exists")
        return response(self.exists)

    async def search(self, *, index, body=None, query=None, size=1000, scroll="1m", **kwargs):
        self.events.append(f"{self.name}_search")
        assert size <= 1000 and scroll == "1m"
        assert (body or {"query": query})["query"] == {"term": {"metadata.document_id": 81}}
        if not self.exists:
            raise NotFoundError("missing index", response({}, 404).meta, {})
        rows = [row for row in self.rows if row["_source"]["metadata"]["document_id"] == 81]
        cursor = f"{self.name}-{len(self.cursors)}"
        self.cursors[cursor] = (deepcopy(rows), size)
        self.pages.append(len(rows[:size]))
        return response(
            {
                "_scroll_id": cursor,
                "_shards": {"failed": 0},
                "timed_out": False,
                "hits": {
                    "hits": deepcopy(rows[:size]),
                    "total": {
                        "value": len(rows) if self.total_override is None else self.total_override,
                        "relation": "eq",
                    },
                },
            }
        )

    async def scroll(self, *, scroll_id, scroll):
        self.events.append(f"{self.name}_scroll")
        rows, offset = self.cursors[scroll_id]
        result = rows[offset : offset + 1000]
        self.cursors[scroll_id] = (rows, offset + len(result))
        self.pages.append(len(result))
        return response(
            {
                "_scroll_id": scroll_id,
                "_shards": {"failed": 0},
                "timed_out": False,
                "hits": {
                    "hits": deepcopy(result),
                    "total": {
                        "value": len(rows) if self.total_override is None else self.total_override,
                        "relation": "eq",
                    },
                },
            }
        )

    async def clear_scroll(self, *, scroll_id):
        self.cleared.append(scroll_id)

    async def delete_by_query(self, *, index, body=None, query=None, refresh):
        self.events.append(f"{self.name}_delete")
        assert refresh is True
        assert (body or {"query": query})["query"] == {"term": {"metadata.document_id": 81}}
        if self.fail_delete:
            raise self.fail_delete
        matched = [row for row in self.rows if row["_source"]["metadata"]["document_id"] == 81]
        if not self.retains:
            self.rows = [row for row in self.rows if row not in matched]
        return response(
            self.delete_result
            or {
                "total": len(matched),
                "deleted": len(matched),
                "version_conflicts": 0,
                "timed_out": False,
                "failures": [],
            }
        )

    async def refresh(self, *, index):
        self.events.append(f"{self.name}_refresh")
        return response({"_shards": {"failed": 0}})

    async def aadd_texts(self, texts, metadatas, *, ids, refresh_indices, create_index_if_not_exists):
        self.events.append(f"{self.name}_add")
        assert refresh_indices is True and create_index_if_not_exists is False
        assert len(ids) == len(texts) == len(set(ids))
        if self.fail_add:
            raise self.fail_add
        self.add_ids.extend(ids)
        mapped = {row["_id"]: row for row in self.rows}
        for ident, text, metadata in zip(ids, texts, metadatas, strict=True):
            value = {"_id": ident, "_source": {"text": text, "metadata": deepcopy(metadata)}}
            mapped[ident] = self.tamper(value) if self.tamper else value
        self.rows = list(mapped.values())
        return ids

    async def close(self):
        self.closed = True


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(events=[], saved=[], checkpoint=None, save_error=None, deny=None)
    state.source = Knowledge(
        id=40,
        tenant_id=101,
        user_id=7,
        name="source",
        type=3,
        model="11",
        model_config_revision=4,
        index_generation="g4",
        index_name="idx40",
        collection_name="col40",
    )
    state.destination = Knowledge(
        id=50,
        tenant_id=101,
        user_id=7,
        name="destination",
        type=3,
        model="12",
        model_config_revision=9,
        index_generation="g9",
        index_name="idx50",
        collection_name="col50",
    )
    state.source_es = NativeES("source", [chunk(1), chunk(2), chunk(999, 82)], state.events)
    state.target_es = NativeES("target", [chunk(999, 82)], state.events)
    state.source_mv, state.target_mv = NativeCollection(state.events), NativeCollection(state.events)
    state.source_mv.rows = [
        {"pk": 1, "vector": [1.0, 2.0], "text": "source", "document_id": 81},
        {"pk": 2, "vector": [1.0, 2.0], "text": "neighbor", "document_id": 82},
    ]
    state.embedding = SimpleNamespace(
        aembed_documents=AsyncMock(side_effect=lambda texts: [[0.1, float(i)] for i in range(len(texts))])
    )
    state.factory_calls = []

    async def vector(user_id, *, knowledge, embeddings=None, **kwargs):
        state.events.append(f"mv_init_{knowledge.id}")
        assert user_id == 7
        assert kwargs["expected_model_config_revision"] == knowledge.model_config_revision
        assert kwargs["expected_index_generation"] == knowledge.index_generation
        state.factory_calls.append((knowledge.id, embeddings))
        return SimpleNamespace(
            col=state.source_mv if knowledge.id == 40 else state.target_mv,
            embedding_func=state.embedding if embeddings is None else embeddings,
        )

    async def elasticsearch(*, knowledge, **kwargs):
        state.events.append(f"es_init_{knowledge.id}")
        assert kwargs["expected_model_config_revision"] == knowledge.model_config_revision
        assert kwargs["expected_index_generation"] == knowledge.index_generation
        return state.source_es if knowledge.id == 40 else state.target_es

    async def guard():
        state.events.append("guard")
        if state.deny:
            raise state.deny

    async def load():
        return state.checkpoint

    async def save(checkpoint):
        state.events.append("checkpoint")
        if state.save_error:
            raise state.save_error
        state.checkpoint = checkpoint
        state.saved.append(checkpoint)

    state.guard, state.port = guard, SimpleNamespace(aload=load, asave=save)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", vector)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", elasticsearch)
    return state


async def apply(native, **kwargs):
    return await module.apply_move_index_item(
        **{
            "operation_id": "confirmed-move",
            "target": ResourceVersionTarget(file_id=81, document_id=80, version_id=181),
            "source": native.source,
            "destination": native.destination,
            "invoke_user_id": 7,
            "metadata_policy": module.MoveMetadataPolicy(retained_fields=("keep",), removed_fields=("drop",)),
            "guard": native.guard,
            "checkpoints": native.port,
            **kwargs,
        }
    )


async def test_native_full_verification_preserves_manual_chunks_and_neighbors(native):
    before = deepcopy(native.source_es.rows)
    result = await apply(native)
    assert (result.file_id, result.source_count, result.milvus_count, result.es_count) == (81, 2, 2, 2)
    assert len(result.target_payload_digest) == 64
    assert [value.step for value in native.saved] == ["move_target_verified", "move_source_cleaned"]
    assert native.events.index("checkpoint") < native.events.index("source_delete")
    assert native.source_es.rows == [before[-1]] and native.source_mv.rows[-1]["document_id"] == 82
    assert native.source_es.closed and native.target_es.closed
    assert all(value.closed for value in native.target_mv.iterators + native.source_mv.iterators)
    moved = [row for row in native.target_es.rows if row["_source"]["metadata"]["document_id"] == 81]
    for old, new in zip(before[:2], moved, strict=True):
        assert new["_source"]["text"] == old["_source"]["text"]
        assert new["_source"]["metadata"]["knowledge_id"] == 50
        assert new["_source"]["metadata"]["system"] == old["_source"]["metadata"]["system"]
        assert new["_source"]["metadata"]["user_metadata"] == {
            "keep": old["_source"]["metadata"]["user_metadata"]["keep"],
            "system_key": "kept",
        }
    with pytest.raises(FrozenInstanceError):
        result.es_count = 100


async def test_10001_source_chunks_are_streamed_in_bounded_native_batches(native):
    native.source_es.rows = [chunk(number) for number in range(10001)] + [chunk(99999, 82)]
    result = await apply(native)
    assert result.source_count == result.milvus_count == result.es_count == 10001
    assert [len(batch) for batch in native.target_mv.batches] == [1000] * 10 + [1]
    assert max(native.source_es.pages) <= 1000
    assert set(native.source_es.cleared) == set(native.source_es.cursors)


async def test_cleanup_failure_replay_keeps_two_target_rows_and_does_not_reembed(native):
    native.source_es.fail_delete = RuntimeError("source cleanup offline")
    for _ in range(2):
        with pytest.raises(KnowledgeFileFailedError):
            await apply(native)
        assert len(native.target_mv.rows) == 2
        assert len([row for row in native.target_es.rows if row["_source"]["metadata"]["document_id"] == 81]) == 2
        assert native.checkpoint.step == "move_target_verified"
    assert native.embedding.aembed_documents.await_count == 1
    native.source_es.fail_delete = None
    assert (await apply(native)).source_count == 2
    assert native.embedding.aembed_documents.await_count == 1


async def test_partial_target_failure_replaces_all_local_rows_and_keeps_stable_es_ids(native):
    native.target_es.fail_add = RuntimeError("ES after Milvus failure")
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert len(native.target_mv.rows) == 2 and native.checkpoint is None
    assert len(native.source_es.rows) == 3
    native.target_es.fail_add = None
    await apply(native)
    assert len(native.target_mv.rows) == 2
    ids = native.target_es.add_ids[:]
    native.checkpoint = None
    native.source_es.rows = [chunk(1), chunk(2), chunk(999, 82)]
    await apply(native)
    assert native.target_es.add_ids[-2:] == ids


async def test_checkpoint_persistence_failure_prevents_any_source_cleanup(native):
    native.save_error = RuntimeError("SQL checkpoint commit failed")
    with pytest.raises(KnowledgeFileFailedError) as error:
        await apply(native)
    assert error.value.__cause__ is native.save_error
    assert "source_delete" not in native.events and len(native.source_es.rows) == 3
    assert native.checkpoint is None


@pytest.mark.parametrize("store", ["mv", "es"])
async def test_same_count_wrong_target_content_is_rejected_before_source_cleanup(native, store):
    if store == "mv":
        native.target_mv.tamper = lambda row: {**row, "text": "wrong same-count text"}
    else:
        native.target_es.tamper = lambda row: {**row, "_source": {**row["_source"], "text": "wrong same-count text"}}
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.checkpoint is None and "source_delete" not in native.events


async def test_verified_checkpoint_requires_current_target_content_before_cleanup(native):
    native.source_es.fail_delete = RuntimeError("cleanup failed")
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    native.source_es.fail_delete = None
    native.target_mv.rows[0]["text"] = "changed after verification"
    native.events.clear()
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert "source_delete" not in native.events and "mv_insert" not in native.events


@pytest.mark.parametrize("store", ["mv", "es"])
async def test_incomplete_source_cleanup_keeps_verified_checkpoint_for_retry(native, store):
    if store == "mv":
        native.source_mv.delete_retains = True
    else:
        native.source_es.retains = True
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.checkpoint.step == "move_target_verified"


@pytest.mark.parametrize(
    "field,value",
    [("operation_id", "other"), ("file_id", 82), ("source_index_generation", "changed"), ("step", "made_up")],
)
async def test_checkpoint_cannot_be_reused_for_another_operation_or_configuration(native, field, value):
    native.source_es.fail_delete = RuntimeError("cleanup failed")
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    native.checkpoint = replace(native.checkpoint, **{field: value})
    native.events.clear()
    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native)
    assert not any(event.endswith(("delete", "add", "insert")) for event in native.events)


async def test_digest_is_order_independent_and_preserves_duplicate_payloads(native):
    identical = chunk(1)
    native.source_es.rows = [identical, {**deepcopy(identical), "_id": "duplicate-body-different-id"}]
    native.source_es.fail_delete = RuntimeError("cleanup failed")
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    native.target_mv.rows.reverse()
    native.target_es.rows.reverse()
    native.source_es.fail_delete = None
    assert (await apply(native)).source_count == 2


async def test_missing_source_index_is_not_a_successful_empty_move(native):
    native.source_es.exists = False
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.checkpoint is None and not native.target_mv.rows


async def test_guard_rejection_and_non_async_guard_do_not_start_native_io(native):
    native.deny = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await apply(native)
    assert native.events == ["guard"]
    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native, guard=lambda: None)


async def test_guard_before_each_controlled_write_and_final_return(native):
    await apply(native)
    for index, event in enumerate(native.events):
        if event.endswith(("delete", "insert", "add")):
            assert native.events[index - 1] == "guard", native.events[max(0, index - 2) : index + 1]
    assert native.events[-1] == "guard"


@pytest.mark.parametrize("change", ["tenant", "same_index", "wrong_space_type"])
async def test_bad_owner_scope_refuses_before_native_io(native, change):
    if change == "tenant":
        native.destination.tenant_id = 202
    elif change == "same_index":
        native.destination.index_name = native.source.index_name
    else:
        native.destination.type = 1
    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native)
    assert not native.events


async def test_readonly_source_milvus_initialization_uses_existing_fake_embeddings(native):
    await apply(native)
    assert all(isinstance(embedding, FakeEmbeddings) for ident, embedding in native.factory_calls if ident == 40)


async def test_boolean_schema_version_is_not_a_valid_durable_checkpoint(native):
    native.source_es.fail_delete = RuntimeError("cleanup failed")
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    native.checkpoint = replace(native.checkpoint, schema_version=True)
    native.source_es.fail_delete = None
    native.events.clear()
    with pytest.raises(ResourceReferenceInvalidError):
        await apply(native)
    assert "source_delete" not in native.events


async def test_premature_scroll_eof_cannot_drop_a_source_with_more_reported_chunks(native):
    native.source_es.total_override = 3
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert "source_delete" not in native.events and native.checkpoint is None
    assert set(native.source_es.cleared) == set(native.source_es.cursors)


async def test_wrong_embedding_dimension_cannot_be_verified_as_usable_target(native):
    native.embedding.aembed_documents.side_effect = lambda texts: [[0.1] for _ in texts]
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert "source_delete" not in native.events


async def test_native_insert_counter_must_cover_the_complete_batch(native):
    native.target_mv.insert_count = 1
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert native.checkpoint is None
    assert len(native.source_es.rows) == 3
    assert "source_delete" not in native.events


async def test_native_delete_counter_cannot_claim_source_cleaned(native):
    native.source_es.delete_result = {
        "total": 2,
        "deleted": 1,
        "version_conflicts": 0,
        "timed_out": False,
        "failures": [],
    }
    with pytest.raises(KnowledgeFileFailedError):
        await apply(native)
    assert [checkpoint.step for checkpoint in native.saved] == ["move_target_verified"]
    assert len(native.target_mv.rows) == 2


@pytest.mark.parametrize("primary", [False, True])
async def test_all_owned_es_clients_close_even_when_first_client_close_raises(native, primary):
    close_error = RuntimeError("source client close failed")
    native.source_es.close = AsyncMock(side_effect=close_error)
    native.target_es.close = AsyncMock()
    if primary:
        native.target_es.fail_add = RuntimeError("primary ES write failed")
    with pytest.raises(KnowledgeFileFailedError) as error:
        await apply(native)
    assert error.value.__cause__ is (native.target_es.fail_add if primary else close_error)
    native.source_es.close.assert_awaited_once()
    native.target_es.close.assert_awaited_once()

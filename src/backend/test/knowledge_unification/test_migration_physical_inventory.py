"""Physical M2 facts read exact existing identities without RAG/model factories."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pymilvus import DataType

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.config.settings import VectorStores
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.application.unification_inventory_codec import record_from_values


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_physical")


def resource(ident=40, tenant_id=101, **changes):
    data = {
        "tenant_id": tenant_id,
        "id": ident,
        "type": 3,
        "user_id": 7,
        "state": 2,
        "model": "8",
        "index_name": f"es-{ident}",
        "collection_name": f"mv-{ident}",
        "creation_request_id": None,
        "creation_payload_hash": None,
        "old_business_digest": "a" * 64,
        "neutral_digest": "b" * 64,
    }
    return record_from_values("resource", **(data | changes))


def file(ident=81, tenant_id=101, **changes):
    data = {
        "id": ident,
        "tenant_id": tenant_id,
        "knowledge_id": 40,
        "file_type": 1,
        "level": 0,
        "file_level_path": "",
        "status": 2,
        "file_source": "space_upload",
        "file_size": 12,
        "object_name": f"original/{ident}.txt",
        "preview_file_object_name": "preview/shared.pdf",
        "bbox_object_name": "",
        "thumbnails": None,
        "html_snapshot_object_name": None,
        "row_digest": "a" * 64,
        "split_rule_digest": "b" * 64,
        "user_metadata_digest": "c" * 64,
    }
    return record_from_values("file", **(data | changes))


@pytest.fixture
def native(module):
    es = SimpleNamespace(
        indices=SimpleNamespace(
            exists=AsyncMock(return_value=True),
            get_mapping=AsyncMock(
                return_value={
                    "es-40": {
                        "mappings": {
                            "properties": {
                                "text": {"type": "text"},
                                "metadata": {
                                    "properties": {"document_id": {"type": "long"}, "knowledge_id": {"type": "long"}}
                                },
                            }
                        }
                    }
                }
            ),
        ),
        count=AsyncMock(return_value={"count": 2, "_shards": {"failed": 0}}),
        close=AsyncMock(),
    )
    mv = SimpleNamespace(
        has_collection=Mock(return_value=True),
        describe_collection=Mock(
            return_value={
                "collection_name": "mv-40",
                "fields": [
                    {"name": "document_id", "type": DataType.INT64},
                    {"name": "knowledge_id", "type": DataType.INT64},
                    {"name": "text", "type": DataType.VARCHAR},
                    {"name": "vector", "type": DataType.FLOAT_VECTOR, "params": {"dim": 8}},
                ],
            }
        ),
        get_collection_stats=Mock(return_value={"row_count": 3}),
        close=Mock(),
    )
    storage = SimpleNamespace(
        astat_object=AsyncMock(return_value={"exists": True, "size": 12, "etag": "opaque-not-sha"})
    )
    reader = module.PhysicalInventoryReader(es_client=es, milvus_client=mv, storage=storage)
    return SimpleNamespace(reader=reader, es=es, mv=mv, storage=storage)


async def collect(native, **kwargs):
    with tenant_execution_scope(101):
        return [record async for record in native.reader.aiter_facts(**kwargs)]


async def test_native_existing_index_facts_keep_counts_without_model_or_store_mutation(native):
    facts = await collect(native, resource_requests=(resource(),))
    assert len(facts) == 1 and facts[0].record_type == "physical_index"
    data = facts[0].data
    assert data["tenant_id"] == 101 and data["space_id"] == 40
    assert data["identifier_compatible"] is True
    assert (data["es_count"], data["milvus_count"]) == (2, 3)
    assert len(data["es_mapping_digest"]) == len(data["milvus_schema_digest"]) == 64
    native.es.indices.exists.assert_awaited_once_with(index="es-40")
    native.mv.has_collection.assert_called_once_with(collection_name="mv-40")
    native.storage.astat_object.assert_not_awaited()


async def test_objects_use_exact_keys_and_shared_preview_is_statted_once_per_page(native):
    facts = await collect(native, object_requests=(file(), file(82)))
    assert len(facts) == 4
    assert all(item.record_type == "physical_object" for item in facts)
    assert {x.data["file_id"] for x in facts} == {81, 82}
    keys = [c.args[0] for c in native.storage.astat_object.call_args_list]
    assert sorted(keys) == ["original/81.txt", "original/82.txt", "preview/shared.pdf"]
    assert all(x.data["etag"] == "opaque-not-sha" for x in facts)


async def test_all_five_original_object_kinds_are_explicit_and_no_file_body_is_read(native):
    facts = await collect(
        native,
        object_requests=(
            file(
                bbox_object_name="partitions/81.json",
                thumbnails="thumbnails/unique.jpg",
                html_snapshot_object_name="preview/81.html",
            ),
        ),
    )
    assert {x.data["object_kind"] for x in facts} == {"original", "preview", "bbox", "thumbnail", "html_snapshot"}
    assert native.storage.astat_object.await_count == 5


@pytest.mark.parametrize("shape", ["foreign", "duplicate", "wrong_record", "overflow"])
async def test_all_inputs_validated_before_any_external_read(native, shape):
    resources, objects = (resource(),), ()
    if shape == "foreign":
        objects = (file(tenant_id=202),)
    elif shape == "duplicate":
        resources = (resource(), resource())
    elif shape == "wrong_record":
        objects = (resource(),)
    else:
        resources = tuple(resource(i) for i in range(1, 201))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(native, resource_requests=resources, object_requests=objects)
    native.es.indices.exists.assert_not_awaited()
    native.mv.has_collection.assert_not_called()
    native.storage.astat_object.assert_not_awaited()


async def test_missing_or_bypassed_tenant_never_reads(native):
    with tenant_execution_scope(101), bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
        _ = [x async for x in native.reader.aiter_facts(resource_requests=(resource(),))]
    with tenant_execution_scope(202), pytest.raises(KnowledgeOperationPlanConflictError):
        _ = [x async for x in native.reader.aiter_facts(resource_requests=(resource(),))]
    native.es.indices.exists.assert_not_awaited()


async def test_scope_changes_before_yield_are_not_relabelled_as_the_old_tenant(native, module, monkeypatch):
    async def count(**kwargs):
        monkeypatch.setattr(module, "get_current_tenant_id", lambda: 202)
        return {"count": 2, "_shards": {"failed": 0}}

    native.es.count.side_effect = count
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(native, resource_requests=(resource(),))


async def test_uncreated_empty_space_is_a_fact_and_never_initializes_indexes(native):
    native.es.indices.exists.return_value = False
    native.mv.has_collection.return_value = False
    data = (await collect(native, resource_requests=(resource(),)))[0].data
    assert data["es_exists"] is False and data["milvus_exists"] is False
    assert data["es_count"] is None and data["milvus_count"] is None
    native.es.indices.get_mapping.assert_not_awaited()
    native.mv.describe_collection.assert_not_called()


async def test_empty_dynamic_es_mapping_is_compatible_but_wrong_explicit_identifier_is_not(native):
    native.es.indices.get_mapping.return_value = {"es-40": {"mappings": {}}}
    native.es.count.return_value = {"count": 0, "_shards": {"failed": 0}}
    assert (await collect(native, resource_requests=(resource(),)))[0].data["identifier_compatible"] is True
    native.es.indices.get_mapping.return_value = {
        "es-40": {
            "mappings": {
                "properties": {
                    "metadata": {"properties": {"document_id": {"type": "text"}, "knowledge_id": {"type": "long"}}}
                }
            }
        }
    }
    assert (await collect(native, resource_requests=(resource(),)))[0].data["identifier_compatible"] is False


@pytest.mark.parametrize("change", ["shards", "bool_count", "milvus_count", "milvus_identity"])
async def test_native_partial_counts_and_wrong_physical_identity_fail_closed(native, change):
    if change == "shards":
        native.es.count.return_value["_shards"]["failed"] = 1
    elif change == "bool_count":
        native.es.count.return_value["count"] = True
    elif change == "milvus_count":
        native.mv.get_collection_stats.return_value["row_count"] = "not-an-int"
    else:
        native.mv.describe_collection.return_value["collection_name"] = "another-space"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(native, resource_requests=(resource(),))


async def test_object_batch_is_bounded_and_waits_for_started_reads_on_failure(native):
    seen, active, maximum = [], 0, 0
    import asyncio

    async def stat(key):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0)
            seen.append(key)
            if key == "original/81.txt":
                raise RuntimeError("transport failed")
            return {"exists": True, "size": 12, "etag": "e"}
        finally:
            active -= 1

    native.storage.astat_object.side_effect = stat
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(native, object_requests=tuple(file(i) for i in range(81, 100)))
    assert active == 0 and len(seen) == 20 and maximum <= 16


async def test_owned_clients_all_close_even_if_first_close_fails(native, module):
    reader = module.PhysicalInventoryReader(
        es_client=native.es, milvus_client=native.mv, storage=native.storage, owns_clients=True
    )
    native.es.close.side_effect = RuntimeError("close failed")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await reader.aclose()
    native.mv.close.assert_called_once()
    await reader.aclose()
    native.es.close.assert_awaited_once()
    with tenant_execution_scope(101), pytest.raises(KnowledgeOperationPlanConflictError):
        _ = [x async for x in reader.aiter_facts(resource_requests=(resource(),))]


async def test_native_factory_uses_saved_vector_connection_without_rag_model_factory(module, native, monkeypatch):
    es_factory = Mock(return_value=native.es)
    mv_factory = Mock(return_value=native.mv)
    monkeypatch.setattr(module, "AsyncElasticsearch", es_factory)
    monkeypatch.setattr(module, "MilvusClient", mv_factory)
    conf = VectorStores(
        milvus={"connection_args": {"host": "private.invalid", "port": 19530, "db_name": "business"}},
        elasticsearch={"url": "http://private.invalid:9200"},
    )
    async with module.PhysicalInventoryReader.aopen(conf, storage=native.storage) as reader:
        with tenant_execution_scope(101):
            assert len([x async for x in reader.aiter_facts(resource_requests=(resource(),))]) == 1
    assert mv_factory.call_args.kwargs["uri"] == "http://private.invalid:19530"
    assert mv_factory.call_args.kwargs["db_name"] == "business"
    native.es.close.assert_awaited_once()
    native.mv.close.assert_called_once()


async def test_explicit_close_inside_factory_context_does_not_close_owned_clients_twice(module, native, monkeypatch):
    monkeypatch.setattr(module, "AsyncElasticsearch", Mock(return_value=native.es))
    monkeypatch.setattr(module, "MilvusClient", Mock(return_value=native.mv))
    config = VectorStores(
        milvus={"connection_args": {"uri": "http://private.invalid:19530"}},
        elasticsearch={"url": "http://private.invalid:9200"},
    )
    async with module.PhysicalInventoryReader.aopen(config, storage=native.storage) as reader:
        await reader.aclose()
    native.es.close.assert_awaited_once()
    native.mv.close.assert_called_once()


async def test_cancelled_constructor_closes_the_late_client_and_preserves_cancel(module, native, monkeypatch):
    import asyncio
    import threading

    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def create(**kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        return native.mv

    monkeypatch.setattr(module, "AsyncElasticsearch", Mock(return_value=native.es))
    monkeypatch.setattr(module, "MilvusClient", create)
    config = VectorStores(
        milvus={"connection_args": {"uri": "http://private.invalid:19530"}},
        elasticsearch={"url": "http://private.invalid:9200"},
    )

    async def run():
        async with module.PhysicalInventoryReader.aopen(config, storage=native.storage):
            pytest.fail("cancelled construction must not yield a reader")

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel("original cancellation")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        native.es.close.assert_awaited_once()
        native.mv.close.assert_called_once()
    finally:
        release.set()


async def test_cancel_during_close_finishes_both_owned_clients_before_propagating(module, native):
    import asyncio

    started, release = asyncio.Event(), asyncio.Event()

    async def close():
        started.set()
        await release.wait()

    native.es.close.side_effect = close
    reader = module.PhysicalInventoryReader(
        es_client=native.es, milvus_client=native.mv, storage=native.storage, owns_clients=True
    )
    task = asyncio.create_task(reader.aclose())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel("original cancellation")
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await reader.aclose()
    native.es.close.assert_awaited_once()
    native.mv.close.assert_called_once()

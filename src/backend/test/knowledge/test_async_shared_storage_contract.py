"""共享存储原生异步写入与实时路由检查的行为契约。"""

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.config.settings import KnowledgeSpaceSharedStorageConf
from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError
from bisheng.knowledge.rag import shared_space_storage as storage


async def test_live_route_guard_yields_during_schema_check_and_rejects_changed_route(monkeypatch):
    snapshot = storage.TenantRoutingSnapshot(1, True, 3, False, "shared", "idx", 7, "fp", "")
    writer = storage.MilvusEsSharedSpaceStorageWriter(
        tenant_id=1,
        collection=SimpleNamespace(name="shared"),
        es_client=None,
        expected_routing_version=3,
        schema_spec=storage.SharedStoreSchemaSpec(embedding_model_id=7, dimension=2),
        conf=KnowledgeSpaceSharedStorageConf(),
    )
    writer._async_routing_provider = AsyncMock(return_value=snapshot)
    started, release = threading.Event(), threading.Event()
    loop_thread = threading.get_ident()

    def verify(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(2)

    monkeypatch.setattr(storage, "verify_shared_collection_schema", verify)
    task = asyncio.create_task(writer._aassert_writable(embedding_model_id=7))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert not task.done()
    finally:
        release.set()
    assert await task == snapshot
    writer._async_routing_provider.return_value = replace(snapshot, routing_version=4)
    with pytest.raises(SharedStorageContractError):
        await writer._aassert_writable(embedding_model_id=7)
    writer._async_routing_provider.return_value = replace(snapshot, write_frozen=True)
    with pytest.raises(SharedStorageContractError):
        await writer._aassert_writable(embedding_model_id=7)


async def test_native_clients_preserve_payload_and_propagate_write_failure():
    writer = storage.MilvusEsSharedSpaceStorageWriter(
        tenant_id=1,
        collection=SimpleNamespace(name="shared"),
        es_client=SimpleNamespace(bulk=AsyncMock(return_value={"errors": True})),
        expected_routing_version=3,
        schema_spec=storage.SharedStoreSchemaSpec(embedding_model_id=7, dimension=2),
    )
    writer._native_async_es = True
    writer._async_write_runtime = SimpleNamespace(write_shared_content=AsyncMock(return_value={"insert_count": 1}))
    rows = [{"text": "原文", "vector": [0.1, 0.2]}]
    await writer._run_milvus("insert", rows)
    writer._async_write_runtime.write_shared_content.assert_awaited_once_with("insert", "shared", data=rows)
    await writer._run_milvus("delete", expr="pk in [1]")
    writer._async_write_runtime.write_shared_content.assert_awaited_with("delete", "shared", filter="pk in [1]")
    assert await writer._run_es("bulk", operations=rows) == {"errors": True}
    writer.es_client.bulk.side_effect = OSError("es down")
    with pytest.raises(OSError, match="es down"):
        await writer._run_es("bulk", operations=rows)


async def test_async_factory_owns_client_and_keeps_fresh_routing(monkeypatch):
    import importlib

    config_service = importlib.import_module("bisheng.common.services.config_service")
    from bisheng.core.context import manager
    from bisheng.core.search.elasticsearch.es_connection import ESConnection
    from bisheng.knowledge.rag import async_retrieval_runtime

    context = manager.ApplicationContextManager()
    monkeypatch.setattr(manager, "app_context", context)
    client = SimpleNamespace(close=AsyncMock())
    created_hosts = []

    def create_client(connection):
        created_hosts.append(connection.es_hosts)
        return client

    monkeypatch.setattr(ESConnection, "_create_es_connection", create_client)
    monkeypatch.setattr(
        config_service.settings,
        "get_vectors_conf",
        lambda: SimpleNamespace(
            elasticsearch=SimpleNamespace(elasticsearch_url="http://vector-es:9200", ssl_verify={}),
        ),
    )
    route = AsyncMock(return_value=storage.TenantRoutingSnapshot(1, True, 3, False, "shared", "idx", 7, "fp", ""))
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", route)
    runtime = object()
    monkeypatch.setattr(async_retrieval_runtime, "get_async_retrieval_runtime", AsyncMock(return_value=runtime))
    loop_thread = threading.get_ident()

    def build(tenant_id, *, routing_provider, es_client):
        assert threading.get_ident() != loop_thread
        assert routing_provider(tenant_id) == route.return_value
        return SimpleNamespace(es_client=es_client), SimpleNamespace()

    monkeypatch.setattr(storage, "build_shared_space_components_for_tenant", build)
    try:
        first, reader = await storage.abuild_shared_space_components_for_tenant(1)
        second, _ = await storage.abuild_shared_space_components_for_tenant(1)
        assert first.es_client is second.es_client is client
        assert first._native_async_es is True
        assert first._async_write_runtime is runtime
        assert first._async_routing_provider is reader._routing_provider is route
        assert created_hosts == ["http://vector-es:9200"]
        client.close.assert_not_awaited()
    finally:
        await context.get_context("shared_storage_elasticsearch").async_close()
    client.close.assert_awaited_once()


async def test_native_milvus_write_timeout_releases_concurrency_budget():
    from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf
    from bisheng.knowledge.rag.async_retrieval_runtime import AsyncRetrievalRuntime

    cleaned = asyncio.Event()

    async def slow_insert(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    client = SimpleNamespace(insert=slow_insert, delete=AsyncMock(return_value={"delete_count": 1}))
    config = KnowledgeRetrievalRuntimeConf()
    config.milvus_timeout_seconds = 0.02
    config.max_milvus_concurrency = 1
    runtime = AsyncRetrievalRuntime(config=config, connection_args={}, milvus_client=client)
    with pytest.raises(asyncio.TimeoutError):
        await runtime.write_shared_content("insert", "shared", data=[])
    assert cleaned.is_set()
    assert await runtime.write_shared_content("delete", "shared", filter="pk in [1]") == {"delete_count": 1}
    client.delete.assert_awaited_once_with(collection_name="shared", filter="pk in [1]", timeout=0.02)

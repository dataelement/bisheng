"""SPACE 只能使用共享存储，历史开关不能恢复旧链路。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.rag import shared_space_storage as storage


def initialized_route():
    return storage.TenantRoutingSnapshot(
        tenant_id=1, shared_enabled=False, routing_version=3, write_frozen=False,
        collection_name="custom_shared_vectors", index_name="custom_shared_text",
        embedding_model_id=7, schema_fingerprint="fingerprint", migration_state="",
    )


@pytest.mark.parametrize("old_enabled", [False, True, None])
async def test_space_routes_without_enable_switches(monkeypatch, old_enabled):
    route = initialized_route()
    conf = SimpleNamespace(enabled=old_enabled)
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: route)
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", AsyncMock(return_value=route))
    assert storage.resolve_space_shared_routing(1, KnowledgeTypeEnum.SPACE.value, conf=conf) == route
    assert await storage.aresolve_space_shared_routing(1, KnowledgeTypeEnum.SPACE.value, conf=conf) == route


@pytest.mark.parametrize("missing", ["row", "collection_name", "index_name", "embedding_model_id", "schema_fingerprint"])
async def test_uninitialized_space_fails_without_legacy_fallback(monkeypatch, missing):
    route = None if missing == "row" else replace(initialized_route(), **{missing: None})
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: route)
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", AsyncMock(return_value=route))
    for resolve in (storage.resolve_space_shared_routing, storage.aresolve_space_shared_routing):
        with pytest.raises(SharedStorageContractError) as error:
            result = resolve(1, KnowledgeTypeEnum.SPACE.value)
            if resolve is storage.aresolve_space_shared_routing:
                await result
        assert error.value.code == SharedStorageErrorCode.ROUTING_NOT_CONFIGURED


@pytest.mark.parametrize("kind", [KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.PRIVATE.value, KnowledgeTypeEnum.QA.value])
async def test_other_knowledge_types_do_not_load_shared_route(monkeypatch, kind):
    provider = MagicMock(side_effect=AssertionError("non SPACE must not load a shared route"))
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", provider)
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", provider)
    assert storage.resolve_space_shared_routing(1, kind) is None
    assert await storage.aresolve_space_shared_routing(1, kind) is None
    provider.assert_not_called()


def test_create_space_preserves_initialized_target_names(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

    route = initialized_route()
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: route)
    knowledge = SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=1, collection_name=None, index_name=None)
    monkeypatch.setattr("bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.insert_one", lambda value: value)
    KnowledgeService.create_knowledge_base(None, SimpleNamespace(user_id=1, tenant_id=1), knowledge, skip_hook=True)
    assert (knowledge.collection_name, knowledge.index_name) == (route.collection_name, route.index_name)


def test_create_space_rejects_missing_route_before_insert(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: None)
    insert = MagicMock()
    monkeypatch.setattr("bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao.insert_one", insert)
    with pytest.raises(SharedStorageContractError):
        KnowledgeService.create_knowledge_base(
            None, SimpleNamespace(user_id=1, tenant_id=1),
            SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=1), skip_hook=True,
        )
    insert.assert_not_called()


async def test_keyword_query_maps_shared_content_to_ready_entries(monkeypatch):
    from contextlib import asynccontextmanager

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.services import shared_space_file_queries as subject

    client = SimpleNamespace(search=AsyncMock(return_value={"aggregations": {"documents": {"buckets": [
        {"key": 100, "generation": {"value": 3}},
    ]}}}))
    monkeypatch.setattr(subject, "get_es_connection", AsyncMock(return_value=client))
    monkeypatch.setattr(subject, "aresolve_space_shared_routing", AsyncMock(return_value=initialized_route()))

    @asynccontextmanager
    async def session():
        yield object()

    entries = [KnowledgeFile(
        id=fid, tenant_id=1, knowledge_id=kid, reference_document_id=100,
        status=2, projection_status=status, desired_content_generation=generation,
        applied_content_generation=generation, desired_entry_generation=1, applied_entry_generation=1,
    ) for fid, kid, status, generation in [(11, 10, "ready", 3), (12, 20, "ready", 3),
                                          (13, 10, "ready", 2), (14, 10, "pending", 3)]]
    repo = SimpleNamespace(find_active_entries_for_documents=AsyncMock(return_value=entries))
    monkeypatch.setattr(subject, "get_async_db_session", session)
    monkeypatch.setattr(subject, "KnowledgeFileRepositoryImpl", lambda _: repo)
    spaces = [SimpleNamespace(id=10, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value)]

    assert await subject.search_shared_space_file_ids(spaces=spaces, keyword="共享正文") == [11]
    request = client.search.await_args.kwargs
    assert request["index"] == "custom_shared_text"
    assert request["query"]["bool"]["filter"] == [{"terms": {"metadata.knowledge_ids": [10]}}]
    assert "metadata.document_id" not in str(request)


@pytest.mark.parametrize("tenant,kind", [(2, KnowledgeTypeEnum.SPACE.value), (1, KnowledgeTypeEnum.NORMAL.value)])
async def test_keyword_query_rejects_mixed_scope_before_search(monkeypatch, tenant, kind):
    from bisheng.knowledge.domain.services import shared_space_file_queries as subject

    connect = AsyncMock()
    monkeypatch.setattr(subject, "get_es_connection", connect)
    spaces = [SimpleNamespace(id=10, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value),
              SimpleNamespace(id=20, tenant_id=tenant, type=kind)]
    with pytest.raises(SharedStorageContractError):
        await subject.search_shared_space_file_ids(spaces=spaces, keyword="正文")
    connect.assert_not_awaited()


async def test_reprojection_loads_original_with_tenant_embedding(monkeypatch):
    from langchain_core.documents import Document

    from bisheng.knowledge.domain.services import shared_space_content_loader as subject

    monkeypatch.setattr(subject, "resolve_space_shared_routing", lambda *_: initialized_route())
    pipeline = MagicMock()
    pipeline.run.return_value.documents = [Document(page_content="原文件正文", metadata={"chunk_index": 2})]
    pipeline_factory = MagicMock(return_value=pipeline)
    embeddings = MagicMock()
    embeddings.embed_documents.return_value = [[0.2, 0.4]]
    embedding_factory = MagicMock(return_value=embeddings)
    monkeypatch.setattr(subject, "KnowledgeFilePipeline", pipeline_factory)
    monkeypatch.setattr(subject.LLMService, "get_bisheng_knowledge_embedding_sync", embedding_factory)
    chunks = await subject.load_shared_content_from_original(SimpleNamespace(tenant_id=1, user_id=9))
    assert chunks[0].text == "原文件正文"
    assert chunks[0].chunk_index == 2
    assert chunks[0].vector == [0.2, 0.4]
    assert pipeline_factory.call_args.kwargs["vector_store"] == []
    assert embedding_factory.call_args.kwargs["model_id"] == 7
    assert pipeline.run.call_args.args[0].stop_at == subject.PipelineStage.TRANSFORMER


async def test_portal_chunk_preview_reads_canonical_shared_target(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    owner = object.__new__(KnowledgeSpaceService)
    file = SimpleNamespace(id=11, tenant_id=1, parse_type="general")
    owner._portal_file_access_decision_map = {}
    owner._get_authorized_shougang_portal_file = AsyncMock(return_value=(file, [object()]))
    owner._resolve_shougang_portal_content_entry = AsyncMock(return_value=SimpleNamespace(
        projection_ready=True, canonical_document_id=100, canonical_version_id=200, content_generation=3,
    ))
    client = SimpleNamespace(search=AsyncMock(return_value={"hits": {
        "total": {"value": 1}, "hits": [{"_source": {"text": "正文", "metadata": {"canonical_document_id": 100}}}],
    }}))
    monkeypatch.setattr("bisheng.core.search.elasticsearch.manager.get_es_connection", AsyncMock(return_value=client))
    monkeypatch.setattr(storage, "aresolve_space_shared_routing", AsyncMock(return_value=initialized_route()))
    result = await owner.get_shougang_portal_file_chunks(space_id=10, file_id=11, page=2, limit=20)
    assert result["data"][0]["metadata"]["document_id"] == 11
    assert result["total"] == 1
    query = client.search.await_args.kwargs
    assert query["index"] == "custom_shared_text" and query["from_"] == 20
    assert {"term": {"metadata.canonical_document_id": 100}} in query["query"]["bool"]["filter"]
    assert {"term": {"metadata.knowledge_ids": 10}} in query["query"]["bool"]["filter"]


@pytest.mark.parametrize("adapter", ["init_knowledge_es_vectorstore_sync", "init_knowledge_milvus_vectorstore_sync"])
def test_space_cannot_open_legacy_adapter(adapter):
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    knowledge = SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value, tenant_id=1)
    with pytest.raises(SharedStorageContractError):
        if "milvus" in adapter:
            getattr(KnowledgeRag, adapter)(1, knowledge=knowledge)
        else:
            getattr(KnowledgeRag, adapter)(knowledge=knowledge)


@pytest.mark.parametrize("kinds,expected", [([3], True), ([0, 2], False), ([3, 0], None)])
async def test_consumers_route_by_type_instead_of_flags(monkeypatch, kinds, expected):
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.workflow.common.knowledge import is_shared_storage_active_for_knowledge_ids

    rows = [SimpleNamespace(id=i + 10, tenant_id=1, type=kind) for i, kind in enumerate(kinds)]
    ids = [row.id for row in rows]
    monkeypatch.setattr(KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=rows))
    monkeypatch.setattr(KnowledgeDao, "get_list_by_ids", MagicMock(return_value=rows))
    monkeypatch.setattr(storage, "load_tenant_routing_snapshot", lambda _: initialized_route())
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", AsyncMock(return_value=initialized_route()))
    service = object.__new__(KnowledgeSpaceChatService)
    if expected is None:
        with pytest.raises(SharedStorageContractError):
            await service._is_shared_storage_active(ids)
        with pytest.raises(SharedStorageContractError):
            is_shared_storage_active_for_knowledge_ids(ids)
    else:
        assert await service._is_shared_storage_active(ids) is expected
        assert is_shared_storage_active_for_knowledge_ids(ids) is expected


async def test_shared_rebuild_uses_projection_and_requires_convergence(monkeypatch):
    from contextlib import asynccontextmanager

    import importlib
    import importlib.util
    import sys
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[2]
    for name, directory in [("bisheng.worker", "bisheng/worker"), ("bisheng.worker.knowledge", "bisheng/worker/knowledge")]:
        monkeypatch.setattr(sys.modules[name], "__path__", [str(backend_root / directory)], raising=False)
    projection = importlib.import_module("bisheng.worker.knowledge.document_projection")
    spec = importlib.util.spec_from_file_location("f108_rebuild_worker", backend_root / "bisheng/worker/knowledge/rebuild_knowledge_worker.py")
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)

    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_context():
        yield session

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", session_context)
    repository = SimpleNamespace(request_projection_rebuild=AsyncMock(return_value=True))
    for module, name in [
        ("knowledge_file_repository_impl", "KnowledgeFileRepositoryImpl"),
        ("knowledge_document_repository_impl", "KnowledgeDocumentRepositoryImpl"),
        ("knowledge_document_version_repository_impl", "KnowledgeDocumentVersionRepositoryImpl"),
    ]:
        monkeypatch.setattr(f"bisheng.knowledge.domain.repositories.implementations.{module}.{name}", lambda _: repository)
    service = SimpleNamespace(process_entry=AsyncMock(return_value=SimpleNamespace(status="ready")))
    monkeypatch.setattr(projection, "_build_document_projection_service", AsyncMock(return_value=service))
    file = SimpleNamespace(id=11, tenant_id=1)
    await subject._rebuild_shared_file(file)
    repository.request_projection_rebuild.assert_awaited_once_with(11)
    assert service.process_entry.await_args.kwargs["force_content_upsert"] is True
    service.process_entry.return_value.status = "not_claimed"
    with pytest.raises(RuntimeError, match="did not converge"):
        await subject._rebuild_shared_file(file)


async def test_version_comparison_reads_shared_content_file_id(monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    owner = object.__new__(KnowledgeVersionService)
    client = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": [
        {"_source": {"text": "主版本", "metadata": {"content_file_id": 11}}},
    ]}}))
    monkeypatch.setattr("bisheng.core.search.elasticsearch.manager.get_es_connection", AsyncMock(return_value=client))
    monkeypatch.setattr(storage, "aresolve_space_shared_routing", AsyncMock(return_value=initialized_route()))
    assert await owner._fetch_chunk_texts(SimpleNamespace(id=10, tenant_id=1, type=3), [11]) == {11: "主版本"}
    request = client.search.await_args.kwargs
    assert request["index"] == "custom_shared_text"
    assert {"term": {"metadata.knowledge_ids": 10}} in request["query"]["bool"]["filter"]


async def test_cross_space_restore_requeues_shared_membership_after_commit(monkeypatch):
    import sys
    from contextlib import asynccontextmanager

    from bisheng.knowledge.domain.services import knowledge_recycle_service as subject

    service = subject.KnowledgeRecycleService(SimpleNamespace(tenant_id=1))
    service._require_admin = MagicMock()
    service.preview_restore = AsyncMock(return_value=SimpleNamespace(
        need_confirm_merge=False, need_confirm_overwrite=False, blockers=[],
    ))
    item = SimpleNamespace(id=1, file_id=11, original_knowledge_id=10, recycle_batch_id="batch",
                           recycle_root_id=11, file_type=1)
    service._load_list_items = AsyncMock(return_value=[item])
    service._resolve_target = AsyncMock(return_value=(20, None))
    service._target_file_level_path = AsyncMock(return_value="")
    service._batch_file_ids = AsyncMock(return_value=[11])
    service._restore_entries_as_sibling = AsyncMock()
    file = SimpleNamespace(id=11, knowledge_id=20, tenant_id=1, reference_document_id=100,
                           desired_entry_generation=3)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [file]
    session = SimpleNamespace(execute=AsyncMock(return_value=result), flush=AsyncMock(),
                              commit=AsyncMock(), add=MagicMock())

    @asynccontextmanager
    async def context():
        yield session

    monkeypatch.setattr(subject, "get_async_db_session", context)
    monkeypatch.setattr(subject, "request_file_sync_intents", AsyncMock())
    monkeypatch.setattr(subject.KnowledgeSpaceContentStat, "enqueue_file_stat_async", AsyncMock())
    monkeypatch.setattr(storage, "aresolve_space_shared_routing", AsyncMock(return_value=initialized_route()))
    repository = SimpleNamespace(request_projection_rebuild=AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl.KnowledgeFileRepositoryImpl",
        lambda _: repository,
    )

    def enqueue(**kwargs):
        session.commit.assert_awaited_once()
        assert kwargs == {"tenant_id": 1, "entry_ids": [11]}

    dispatch = MagicMock(side_effect=enqueue)
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge.document_projection",
                        SimpleNamespace(enqueue_document_projection_entries=dispatch))
    result = await service.restore(SimpleNamespace(item_ids=[1], merge_folder=False, overwrite_files=False))
    assert result == {"restored": 1}
    assert file.desired_entry_generation == 4
    repository.request_projection_rebuild.assert_awaited_once_with(11)
    dispatch.assert_called_once()

"""全局检索的查询规模、授权边界和共享入口映射回归。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileSearchReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService, PortalDiscoveryResult
from bisheng.knowledge.domain.services import portal_global_search_retrieval as subject
from test.knowledge.test_knowledge_retrieval_scope_resolver import (
    TENANT,
    hit,
    make_document,
    make_entry,
    make_resolver,
)


def setup_search(monkeypatch, ids=(10,), *, explicit=None, discoverable=None, grants=None, entries=None):
    entries = entries if entries is not None else [make_entry(101, space_id=ids[-1], entry_type="share")]
    for entry in entries:
        entry.status = 2
        entry.file_type = 1
    resolver, repo, _, _ = make_resolver(entries=entries, documents=[make_document()])
    repo.find_active_entries_for_documents_any_space = AsyncMock(wraps=repo.find_active_entries_for_documents_any_space)
    owner = object.__new__(KnowledgeSpaceService)
    owner.login_user = SimpleNamespace(tenant_id=TENANT, user_id=42)
    owner.knowledge_file_repo = repo
    owner.doc_repo = resolver.document_repository
    owner.version_repo = resolver.version_repository
    owner._portal_file_access_decision_map = {}
    owner._portal_discovery_result = PortalDiscoveryResult(
        discoverable_space_ids=list(ids if discoverable is None else discoverable),
        explicitly_visible_space_ids=list(ids if explicit is None else explicit),
        explicitly_visible_file_ids=list((grants or {}).keys()),
        explicit_file_space_by_id=grants or {},
        grant_parent_space_ids=sorted(set((grants or {}).values())),
        query_space_ids=list(ids),
        space_kind_by_id={},
        snapshot="test",
    )
    owner._get_shougang_portal_public_space_ids = AsyncMock(return_value=set())
    owner._filter_shougang_portal_visible_files = AsyncMock(side_effect=lambda files, **kw: files)
    spaces = [SimpleNamespace(id=i, name=f"空间{i}", tenant_id=TENANT, type=KnowledgeTypeEnum.SPACE.value) for i in ids]
    from bisheng.knowledge.domain.repositories.implementations import (
        portal_search_context_repository_impl as context_repo_module,
    )

    async def load_context(kind, wanted):
        if kind == "files":
            return {int(row.id): row for row in await repo.find_by_ids(wanted)}
        if kind == "documents":
            return {int(row.id): row for row in await owner.doc_repo.find_by_ids(wanted)}
        if kind == "entries":
            rows = await repo.find_active_entries_for_documents_any_space(tenant_id=TENANT, document_ids=wanted)
            return {doc: [row for row in rows if row.reference_document_id == doc] for doc in wanted}
        if kind == "spaces":
            return {int(space.id): space for space in spaces if int(space.id) in wanted}
        if kind == "scopes":
            return {
                sid: SimpleNamespace(
                    space_id=sid, level="department", owner_type="department", owner_id=1, tenant_id=TENANT
                )
                for sid in wanted
            }
        if kind == "bindings":
            return {sid: [SimpleNamespace(space_id=sid, department_id=1, tenant_id=TENANT)] for sid in wanted}
        if kind == "departments":
            return {sid: SimpleNamespace(id=sid, status="active", is_deleted=0, tenant_id=TENANT) for sid in wanted}
        return {}

    context_repo = SimpleNamespace(load=AsyncMock(side_effect=load_context))
    monkeypatch.setattr(context_repo_module, "PortalSearchContextRepositoryImpl", lambda user_id: context_repo)
    snapshot = SimpleNamespace(
        tenant_id=TENANT,
        shared_enabled=True,
        routing_version=1,
        collection_name="shared",
        index_name="shared",
        embedding_model_id=9,
        schema_fingerprint=subject.SharedStoreSchemaSpec(embedding_model_id=9, dimension=2).fingerprint(),
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            total_timeout_seconds=2,
            embedding_timeout_seconds=1,
            elasticsearch_timeout_seconds=1,
            milvus_timeout_seconds=1,
        ),
        embed_query=AsyncMock(return_value=[0.1, 0.2]),
    )
    monkeypatch.setattr(subject.LLMService, "get_bisheng_knowledge_embedding", AsyncMock(return_value=object()))
    monkeypatch.setattr(subject, "get_shared_storage_conf", lambda: SimpleNamespace(knowledge_ids_max_capacity=4096))
    reader = SimpleNamespace(search_es=AsyncMock(return_value=[hit()]), search_milvus=AsyncMock(return_value=[hit()]))
    req = ShougangPortalFileSearchReq(q="振动", discovery_scope="portal_configured")
    engine = subject.PortalGlobalSearchRetriever(
        owner=owner, req=req, spaces=spaces, snapshot=snapshot, reader=reader, runtime=runtime
    )
    return engine, owner, reader, runtime


@pytest.mark.parametrize("count", [1, 20, 241])
async def test_whole_scope_queries_once_per_backend(monkeypatch, count):
    ids = tuple(range(10, 10 + count))
    engine, owner, reader, runtime = setup_search(monkeypatch, ids)
    result = await engine.retrieve(tag_file_ids=None)
    assert len(result.chunks) == 2
    assert {chunk.knowledge_id for chunk in result.chunks} == {ids[-1]}
    for call in (reader.search_es, reader.search_milvus):
        call.assert_awaited_once()
        assert tuple(call.call_args.kwargs["filter_"].requested_space_ids) == ids
    assert reader.search_es.call_args.kwargs["limit"] == 240
    assert reader.search_milvus.call_args.kwargs["limit"] == 72
    runtime.embed_query.assert_awaited_once()
    owner.knowledge_file_repo.find_active_entries_for_documents_any_space.assert_awaited_once()


async def test_overlapping_lanes_load_mapping_once_and_keep_lane_text(monkeypatch):
    engine, owner, reader, _ = setup_search(monkeypatch)
    owner.doc_repo.find_by_ids = AsyncMock(wraps=owner.doc_repo.find_by_ids)
    from dataclasses import replace

    reader.search_es.return_value = [replace(hit(), text="ES 正文")]
    reader.search_milvus.return_value = [replace(hit(), text="向量正文")]
    result = await engine.retrieve(tag_file_ids=None)
    assert {(c.retriever, c.content) for c in result.chunks} == {("es", "ES 正文"), ("vector", "向量正文")}
    owner.doc_repo.find_by_ids.assert_awaited_once()
    owner.knowledge_file_repo.find_active_entries_for_documents_any_space.assert_awaited_once()


async def test_shared_mapping_does_not_accept_stale_lane_via_fresh_lane(monkeypatch):
    from dataclasses import replace

    engine, _, reader, _ = setup_search(monkeypatch)
    reader.search_es.return_value = [replace(hit(), text="旧正文", content_generation=999)]
    reader.search_milvus.return_value = [replace(hit(), text="当前正文")]
    result = await engine.retrieve(tag_file_ids=None)
    assert [(chunk.retriever, chunk.content) for chunk in result.chunks] == [("vector", "当前正文")]


async def test_explicit_grant_and_metadata_are_not_whole_space_access(monkeypatch):
    entries = [
        make_entry(101, space_id=10, entry_type="share"),
        make_entry(202, space_id=20, entry_type="share"),
        make_entry(203, space_id=20, entry_type="share"),
    ]
    engine, _, reader, runtime = setup_search(
        monkeypatch, (10, 20, 30), explicit=[10], discoverable=[10, 30], grants={202: 20}, entries=entries
    )
    result = await engine.retrieve(tag_file_ids=None)
    assert result.metadata_space_ids == [30]
    assert reader.search_es.await_count == reader.search_milvus.await_count == 2
    filters = [call.kwargs["filter_"] for call in reader.search_es.await_args_list]
    assert [tuple(f.requested_space_ids) for f in filters] == [(10,), (20,)]
    assert filters[1].canonical_document_ids == (91,)
    assert {chunk.file_id for chunk in result.chunks} == {101}
    runtime.embed_query.assert_awaited_once()


async def test_tag_selects_matching_shared_entry_not_out_of_scope_manager(monkeypatch):
    entries = [make_entry(101, space_id=10, entry_type="manager"), make_entry(202, space_id=20, entry_type="share")]
    engine, _, _, _ = setup_search(monkeypatch, (10, 20), entries=entries)
    result = await engine.retrieve(tag_file_ids=[202])
    assert {chunk.file_id for chunk in result.chunks} == {202}


@pytest.mark.parametrize("reason", ["denied", "old_version", "generation", "content_generation", "deleted"])
async def test_invalid_or_unauthorized_content_dropped(monkeypatch, reason):
    entry = make_entry(101, space_id=10, entry_type="share")
    engine, owner, reader, _ = setup_search(monkeypatch, entries=[entry])
    # 放宽同步状态也不能接受实际过期命中或无权内容。
    entry.projection_status = "pending"
    if reason == "denied":
        owner._portal_file_access_decision_map[101] = SimpleNamespace(status="approval_required")
    elif reason == "old_version":
        reader.search_es.return_value = reader.search_milvus.return_value = [hit(version_id=999)]
    elif reason == "generation":
        reader.search_es.return_value = reader.search_milvus.return_value = [hit(membership_generation=99)]
    elif reason == "content_generation":
        reader.search_es.return_value = reader.search_milvus.return_value = [hit(content_generation=99)]
    else:
        engine.owner.doc_repo.documents[0].lifecycle_status = "deleted"
    assert (await engine.retrieve(tag_file_ids=None)).chunks == []


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("lag", ["pending", "failed", "entry", "content"])
async def test_current_hits_survive_projection_progress_lag(monkeypatch, caplog, explicit, lag):
    entry = make_entry(101, space_id=10, entry_type="share")
    engine, _, _, _ = setup_search(
        monkeypatch,
        entries=[entry],
        explicit=[] if explicit else [10],
        grants={101: 10} if explicit else {},
    )
    if lag in {"pending", "failed"}:
        entry.projection_status = lag
    elif lag == "entry":
        entry.applied_entry_generation = 0
    else:
        entry.applied_content_generation = 0
    result = await engine.retrieve(tag_file_ids=None)
    assert {chunk.file_id for chunk in result.chunks} == {101}
    assert {chunk.retriever for chunk in result.chunks} == {"es", "vector"}
    assert "projection progress ignored for current hit" in caplog.text


async def test_empty_tag_scope_does_not_query_all(monkeypatch):
    engine, _, reader, runtime = setup_search(monkeypatch)
    assert (await engine.retrieve(tag_file_ids=[])).chunks == []
    reader.search_es.assert_not_awaited()
    reader.search_milvus.assert_not_awaited()
    runtime.embed_query.assert_not_awaited()


async def test_backend_failure_degrades_but_routing_error_propagates(monkeypatch):
    engine, _, reader, _ = setup_search(monkeypatch)
    reader.search_milvus.side_effect = RuntimeError("unavailable")
    assert {c.retriever for c in (await engine.retrieve(tag_file_ids=None)).chunks} == {"es"}
    reader.search_es.side_effect = SharedStorageContractError(
        SharedStorageErrorCode.ROUTING_VERSION_MISMATCH, "changed"
    )
    with pytest.raises(SharedStorageContractError):
        await engine.retrieve(tag_file_ids=None)


async def test_cancellation_reaps_queries(monkeypatch):
    engine, _, reader, _ = setup_search(monkeypatch)
    started = asyncio.Event()
    cancelled = []

    async def blocked(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    reader.search_es.side_effect = reader.search_milvus.side_effect = blocked
    task = asyncio.create_task(engine.retrieve(tag_file_ids=None))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(cancelled) == 2


async def test_route_is_tenant_bound_and_legacy_is_explicit(monkeypatch):
    engine, owner, _, _ = setup_search(monkeypatch)
    route = AsyncMock(return_value=None)
    monkeypatch.setattr(subject, "aresolve_space_shared_routing", route)
    assert await subject.resolve_portal_shared_snapshot(owner, engine.spaces) is None
    route.assert_awaited_once()
    route.reset_mock()
    engine.spaces[0].tenant_id = TENANT + 1
    with pytest.raises(SharedStorageContractError):
        await subject.resolve_portal_shared_snapshot(owner, engine.spaces)
    route.assert_not_awaited()


@pytest.mark.parametrize("revoke_at", [None, "rerank", "response"])
async def test_shared_service_integration_rechecks_before_external_content(monkeypatch, revoke_at):
    engine, owner, reader, runtime = setup_search(monkeypatch)
    owner._portal_file_download_map = {}
    owner._get_valid_department_space_ids = AsyncMock(return_value={10})
    owner._filter_shougang_portal_visible_files = KnowledgeSpaceService._filter_shougang_portal_visible_files.__get__(
        owner
    )
    current_decisions = {}
    owner.department_file_view_access_service = SimpleNamespace(
        evaluate_files=AsyncMock(
            side_effect=lambda **kw: {
                int(entry.id): current_decisions.get(
                    int(entry.id), SimpleNamespace(status="allowed", can_download=False, source="grant")
                )
                for entry in kw["files"]
            }
        )
    )
    engine.req.retrieval_profile = "portal_global_shared"
    engine.req.rerank_model_id = "1"
    monkeypatch.setattr(subject, "get_async_retrieval_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(subject, "SharedSpaceStorageReader", lambda **kw: reader)
    monkeypatch.setattr(subject, "aresolve_space_shared_routing", AsyncMock(return_value=engine.snapshot))
    owner._recall_portal_configured_search_sources = AsyncMock(side_effect=AssertionError("不得读旧索引"))
    owner._filter_and_dedupe_portal_search_chunks = AsyncMock(side_effect=AssertionError("不得套旧入口代次"))
    owner._search_portal_metadata_files = AsyncMock(return_value=[])

    async def collect(**kwargs):
        result = await KnowledgeSpaceService._collect_visible_shougang_portal_semantic_candidates(owner, **kwargs)
        if revoke_at == "rerank":
            current_decisions[101] = SimpleNamespace(status="approval_required", can_download=False)
        return result

    async def rerank(**kwargs):
        if revoke_at == "rerank":
            assert kwargs["candidates"] == []
        else:
            assert {c.file_id for c in kwargs["candidates"]} == {101}
            assert all(c.chunks for c in kwargs["candidates"])
        if revoke_at == "response":
            current_decisions[101] = SimpleNamespace(status="approval_required", can_download=False)
        return kwargs["candidates"]

    owner._collect_visible_shougang_portal_semantic_candidates = AsyncMock(side_effect=collect)
    owner._rerank_shougang_portal_file_candidates = AsyncMock(side_effect=rerank)
    owner._handle_file_folder_extra_info = AsyncMock(
        side_effect=lambda files, **kw: [file.model_dump() for file in files]
    )
    owner._resolve_shougang_portal_source_paths = AsyncMock(return_value=({}, {}))
    owner._map_shougang_portal_candidate_items = AsyncMock(wraps=owner._map_shougang_portal_candidate_items)
    response = await owner._semantic_search_shougang_portal_files(
        req=engine.req, spaces=engine.spaces, tag_file_ids=None
    )
    returned = owner._map_shougang_portal_candidate_items.call_args.kwargs["candidates"]
    assert len(returned) == (1 if revoke_at is None else 0)
    assert len(response["data"]) == len(returned)
    owner._recall_portal_configured_search_sources.assert_not_awaited()
    reader.search_es.assert_awaited_once()


@pytest.mark.parametrize("profile,enabled", [("legacy", True), ("portal_global_shared", False)])
async def test_service_keeps_legacy_route_when_not_selected_or_disabled(monkeypatch, profile, enabled):
    engine, owner, _, _ = setup_search(monkeypatch)
    engine.req.retrieval_profile = profile
    route = AsyncMock(return_value=engine.snapshot if enabled else None)
    monkeypatch.setattr(subject, "aresolve_space_shared_routing", route)
    owner._recall_portal_configured_search_sources = AsyncMock(return_value=([], []))
    owner._filter_and_dedupe_portal_search_chunks = AsyncMock(return_value=[])
    result = await owner._semantic_search_shougang_portal_files(req=engine.req, spaces=engine.spaces, tag_file_ids=None)
    assert result["data"] == []
    owner._recall_portal_configured_search_sources.assert_awaited_once()
    assert route.await_count == (0 if profile == "legacy" else 1)


async def test_count_preserves_shared_profile_and_strips_it_for_advanced():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileCountReq

    owner = object.__new__(KnowledgeSpaceService)
    owner.search_shougang_portal_files = AsyncMock(return_value={"data": [{"id": 1}]})
    req = ShougangPortalFileCountReq(
        query_type="keyword", q="振动", discovery_scope="portal_configured", retrieval_profile="portal_global_shared"
    )
    assert (await owner.count_shougang_portal_files(req))["total"] == 1
    forwarded = owner.search_shougang_portal_files.call_args.args[0]
    assert forwarded.retrieval_profile == "portal_global_shared"
    assert forwarded.limit == 50
    owner.advanced_search_shougang_portal_files = AsyncMock(return_value={"data": []})
    req = ShougangPortalFileCountReq(query_type="advanced", retrieval_profile="legacy")
    assert (await owner.count_shougang_portal_files(req))["total"] == 0
    assert "retrieval_profile" not in owner.advanced_search_shougang_portal_files.call_args.args[0].model_dump()


@pytest.mark.parametrize("values", [{"q": ""}, {"discovery_scope": "legacy"}, {"recommendation": "latest_selected"}])
def test_shared_profile_rejects_non_global_requests(values):
    from pydantic import ValidationError

    payload = dict(q="振动", discovery_scope="portal_configured", retrieval_profile="portal_global_shared")
    payload.update(values)
    with pytest.raises(ValidationError):
        ShougangPortalFileSearchReq(**payload)


async def test_total_deadline_is_not_silently_returned_as_empty(monkeypatch):
    engine, _, reader, runtime = setup_search(monkeypatch)
    runtime.config.total_timeout_seconds = 0.05

    async def blocked(**kwargs):
        await asyncio.Event().wait()

    reader.search_es.side_effect = reader.search_milvus.side_effect = blocked
    with pytest.raises(asyncio.TimeoutError):
        await engine.retrieve(tag_file_ids=None)


async def test_embedding_dimension_mismatch_fails_before_any_backend_query(monkeypatch):
    engine, _, reader, runtime = setup_search(monkeypatch)
    runtime.embed_query.return_value = [0.1] * 3
    with pytest.raises(SharedStorageContractError) as exc:
        await engine.retrieve(tag_file_ids=None)
    assert exc.value.code == SharedStorageErrorCode.SCHEMA_FINGERPRINT_MISMATCH
    reader.search_es.assert_not_awaited()
    reader.search_milvus.assert_not_awaited()
    assert subject.LLMService.get_bisheng_knowledge_embedding.call_args.kwargs["model_id"] == 9

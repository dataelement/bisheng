from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services import portal_recommendation_interest_searcher as module
from bisheng.knowledge.rag import shared_space_storage as storage


class FileRepository:
    def __init__(self, entries):
        self.entries = entries
        self.batch_sizes = []

    async def find_by_ids(self, ids):
        self.batch_sizes.append(len(ids))
        return [entry for entry in self.entries if entry.id in ids]

    async def find_active_entries_for_documents_any_space(self, *, tenant_id, document_ids):
        return [
            entry
            for entry in self.entries
            if entry.tenant_id == tenant_id
            and entry.reference_document_id in document_ids
            and entry.entry_status == "active"
            and entry.deleted_at is None
        ]

    async def find_active_entries_for_documents(self, *, tenant_id, document_ids, knowledge_ids):
        return [
            entry
            for entry in await self.find_active_entries_for_documents_any_space(
                tenant_id=tenant_id, document_ids=document_ids
            )
            if entry.knowledge_id in knowledge_ids
        ]


class DocumentRepository:
    def __init__(self, documents):
        self.documents = documents

    async def find_by_ids(self, ids):
        return [document for document in self.documents if document.id in ids]


def entry(file_id=101, space_id=10, document_id=91, **changes):
    values = {
        "id": file_id,
        "knowledge_id": space_id,
        "reference_document_id": document_id,
        "tenant_id": 5,
        "file_type": 1,
        "status": 2,
        "entry_status": "active",
        "entry_type": "manager",
        "deleted_at": None,
        "desired_entry_generation": 3,
        "projection_status": "pending",
        "file_name": "steel",
    }
    return SimpleNamespace(**(values | changes))


def document(document_id=91, **changes):
    return SimpleNamespace(
        **(
            {
                "id": document_id,
                "tenant_id": 5,
                "primary_version_id": 501,
                "content_generation": 2,
                "lifecycle_status": "active",
            }
            | changes
        )
    )


def projection(file_id=101, space_id=10, **changes):
    return SimpleNamespace(
        **({"tenant_id": 5, "file_id": file_id, "space_id": space_id, "recommendable": True} | changes)
    )


def es_hit(document_id=91, **changes):
    metadata = {
        "canonical_document_id": document_id,
        "canonical_version_id": 501,
        "content_generation": 2,
        "membership_generation": 3,
        "chunk_index": 0,
    }
    metadata.update(changes)
    return {"_score": 8.0, "_source": {"metadata": metadata}, "matched_queries": ["q0:title", "q0:tag", "q1:summary"]}


@pytest.fixture
def production(monkeypatch):
    entries = [entry()]
    documents = [document()]
    files = FileRepository(entries)
    docs = DocumentRepository(documents)
    client = SimpleNamespace(search=AsyncMock(return_value={"hits": {"hits": [es_hit()]}}))
    snapshot = storage.TenantRoutingSnapshot(
        tenant_id=5,
        shared_enabled=True,
        routing_version=7,
        write_frozen=False,
        collection_name="shared-5",
        index_name="shared-content-5",
        embedding_model_id=1,
        schema_fingerprint="initialized",
        migration_state=None,
    )
    route = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(storage, "aload_tenant_routing_snapshot", route)
    monkeypatch.setattr(storage, "_aget_shared_es_connection", AsyncMock(return_value=client), raising=False)
    monkeypatch.setattr(storage, "get_shared_storage_conf", lambda: SimpleNamespace(es_routing_enabled=True))

    @asynccontextmanager
    async def session():
        yield SimpleNamespace()

    monkeypatch.setattr(module, "get_async_db_session", session)
    monkeypatch.setattr(module, "KnowledgeFileRepositoryImpl", lambda _session: files, raising=False)
    monkeypatch.setattr(module, "KnowledgeDocumentRepositoryImpl", lambda _session: docs, raising=False)
    monkeypatch.setattr(module, "KnowledgeDocumentVersionRepositoryImpl", lambda _session: None, raising=False)
    monkeypatch.setattr(
        module,
        "PortalRecommendationRepositoryImpl",
        lambda _session: SimpleNamespace(list_latest_recommendable=AsyncMock(return_value=[projection()])),
    )
    monkeypatch.setattr(storage, "_ensure_shared_milvus_connection", lambda *args: pytest.fail("不应连接 Milvus"))
    signals = [PortalSearchQuerySignal(query, datetime.now(timezone.utc), 1) for query in ["steel", "safety"]]
    token = current_tenant_id.set(5)
    yield SimpleNamespace(
        entries=entries,
        documents=documents,
        files=files,
        client=client,
        route=route,
        snapshot=snapshot,
        signals=signals,
    )
    current_tenant_id.reset(token)


async def run_search(state, projections=None, limit=50):
    searcher = module.PortalRecommendationContentSearcher(
        projection_loader=(lambda: projections) if projections is not None else None
    )
    return await searcher.search(5, state.signals, limit)


async def test_default_interest_search_uses_shared_route_and_preserves_scores(production, monkeypatch):
    original = KnowledgeRag.init_knowledge_es_vectorstore
    legacy = AsyncMock(wraps=original)
    monkeypatch.setattr(KnowledgeRag, "init_knowledge_es_vectorstore", legacy)
    hits = await run_search(production)
    assert [(hit.space_id, hit.file_id) for hit in hits] == [(10, 101)]
    assert hits[0].query_field_scores == {"steel": (1.0, 1.0, 0.0), "safety": (0.0, 0.0, 1.0)}
    legacy.assert_not_awaited()
    kwargs = production.client.search.call_args.kwargs
    assert kwargs["index"] == "shared-content-5"
    assert kwargs["routing"] == "91"
    body = kwargs["body"]
    assert body["collapse"] == {"field": "metadata.canonical_document_id"}
    assert "text" not in body["_source"]
    filters = str(body["query"]["bool"]["filter"])
    assert "metadata.knowledge_ids" in filters
    assert "metadata.canonical_version_id" in filters
    assert "metadata.content_generation" in filters and "metadata.membership_generation" in filters
    assert "metadata.document_id" not in filters


@pytest.mark.parametrize(
    "changes",
    [
        {"canonical_version_id": 500},
        {"content_generation": 1},
        {"membership_generation": 2},
        {"canonical_document_id": 999},
    ],
)
async def test_stale_or_outside_hits_are_rejected(production, changes):
    production.client.search.return_value = {"hits": {"hits": [es_hit(**changes)]}}
    assert await run_search(production) == []


@pytest.mark.parametrize(
    "target,changes",
    [
        ("entry", {"tenant_id": 6}),
        ("entry", {"entry_status": "revoked"}),
        ("entry", {"deleted_at": datetime.now(timezone.utc)}),
        ("entry", {"status": 3}),
        ("document", {"lifecycle_status": "deleted"}),
        ("document", {"tenant_id": 6}),
        ("document", {"primary_version_id": None}),
    ],
)
async def test_invalid_candidates_do_not_become_whole_space_queries(production, target, changes):
    for key, value in changes.items():
        setattr(production.entries[0] if target == "entry" else production.documents[0], key, value)
    assert await run_search(production) == []
    production.client.search.assert_not_awaited()


async def test_multiple_spaces_map_only_to_recommendable_entries_and_dedupe(production):
    production.entries[:] = [
        entry(file_id=100, space_id=9),
        entry(),
        entry(file_id=201, space_id=20, entry_type="publish"),
    ]
    projections = [projection(201, 20), projection(101, 10), projection(100, 9, recommendable=False)]
    assert [(hit.space_id, hit.file_id) for hit in await run_search(production, projections)] == [(10, 101)]


@pytest.mark.parametrize(
    "response",
    [
        {"timed_out": True},
        {"terminated_early": True},
        {"_shards": {"failed": 1}},
    ],
)
async def test_partial_es_search_is_an_error(production, response):
    production.client.search.return_value = response | {"hits": {"hits": [es_hit()]}}
    with pytest.raises(RuntimeError):
        await run_search(production)


@pytest.mark.parametrize("changed", [False, True], ids=["missing-route", "changed-version"])
async def test_routing_change_and_missing_route_fail_closed(production, changed):
    next_route = replace(production.snapshot, routing_version=8) if changed else None
    production.route.side_effect = [production.snapshot, next_route]
    with pytest.raises(RuntimeError):
        await run_search(production)
    production.client.search.assert_not_awaited()


async def test_tenant_mismatch_stops_before_io(production):
    token = current_tenant_id.set(6)
    try:
        with pytest.raises(PermissionError):
            await run_search(production)
    finally:
        current_tenant_id.reset(token)
    production.client.search.assert_not_awaited()
    production.route.assert_not_awaited()


async def test_foreign_projection_cannot_select_another_tenant_route(production):
    assert await run_search(production, [projection(tenant_id=6)]) == []
    production.route.assert_not_awaited()


async def test_primary_version_change_after_es_search_is_rechecked(production):
    async def search(**kwargs):
        production.documents[0].primary_version_id = 502
        return {"hits": {"hits": [es_hit()]}}

    production.client.search.side_effect = search
    assert await run_search(production) == []


async def test_batch_merge_deduplicates_and_preserves_limit(production, monkeypatch):
    monkeypatch.setattr(module.PortalRecommendationContentSearcher, "CANDIDATE_BATCH_SIZE", 1)
    production.entries[:] = [
        entry(),
        entry(file_id=201, space_id=20, entry_type="publish"),
        entry(file_id=301, space_id=30, document_id=92),
    ]
    production.documents.append(document(92))
    second_doc = es_hit(92)
    second_doc["_score"] = 10.0
    production.client.search.side_effect = [
        {"hits": {"hits": [es_hit()]}},
        {"hits": {"hits": [es_hit()]}},
        {"hits": {"hits": [second_doc]}},
    ]
    hits = await run_search(production, [projection(), projection(201, 20), projection(301, 30)], limit=2)
    assert [(hit.space_id, hit.file_id) for hit in hits] == [(30, 301), (10, 101)]
    assert max(production.files.batch_sizes) == 1


async def test_rebuild_default_repository_path_keeps_cache_format_and_failure_state(production):
    from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_telemetry_repository_impl import (
        PortalRecommendationTelemetryRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import (
        PortalRecommendationBehaviorService,
    )

    repository = PortalRecommendationTelemetryRepositoryImpl()
    repository.list_recent_search_queries = AsyncMock(return_value=production.signals)
    state = SimpleNamespace(replace_interest=AsyncMock())
    service = PortalRecommendationBehaviorService(state_repository=state, telemetry_repository=repository)
    entries = await service.build_interest_top50(tenant_id=5, user_id=7)
    assert [key for key, _score in entries] == ["10:101"]
    assert state.replace_interest.call_args.args[:3] == (5, 7, entries)
    state.replace_interest.reset_mock()
    production.client.search.side_effect = OSError("业务 ES 不可用")
    with pytest.raises(OSError, match="业务 ES 不可用"):
        await service.build_interest_top50(tenant_id=5, user_id=7)
    state.replace_interest.assert_not_awaited()

"""Exercise the actual SQL selection and outbound hybrid-search request."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.application.provider_retrieval import (
    MetadataPredicate,
    ProviderRetrieval,
    RetrievalSelection,
    TagAssociations,
    WeKnoraSearchPort,
)
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import ProviderRetrievalRepository
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine


@pytest.fixture
async def case():
    db = create_async_engine("sqlite+aiosqlite://")
    async with db.begin() as c:
        for statement in (
            "create table knowledge_provider_binding(tenant_id,space_id,provider_key,active_generation,state)",
            "insert into knowledge_provider_binding values(1,2,'weknora',3,'ready')",
            "create table knowledge_provider_generation(tenant_id,space_id,generation,provider_instance_id,remote_scope_id blob,remote_kb_id blob,state,content_revision)",
            "insert into knowledge_provider_generation values(1,2,3,4,cast('scope' as blob),cast('kb' as blob),'ready',2)",
            "create table knowledge_provider_instance(id,tenant_id,provider_key,remote_scope_id blob,state,capability_revision)",
            "insert into knowledge_provider_instance values(4,1,'weknora',cast('scope' as blob),'ready',5)",
            "create table knowledge_provider_mapping(tenant_id,space_id,generation,resource_type,local_resource_id,logical_document_id,version_id,remote_object_id blob,lifecycle_state,tombstoned_at,ready_revision,operation_epoch)",
            "create table knowledge_document(id,knowledge_id,primary_version_id)",
            "create table knowledge_document_version(id,document_id,knowledge_file_id,is_primary,version_no)",
            "create table knowledgefile(id,tenant_id,knowledge_id,file_type,file_name)",
            "create table knowledge_provider_tag_ref(tenant_id,space_id,generation,tag_ref_id,remote_tag_id blob,state)",
            "insert into knowledge_provider_tag_ref values(1,2,3,8,cast('tag' as blob),'active'),(1,2,1,9,cast('tag' as blob),'active')",
        ):
            await c.execute(text(statement))
        for i in range(1, 5):
            for stmt in (
                f"insert into knowledge_provider_mapping values(1,2,3,'file',{i},{i},{i},cast('R{i}' as blob),'active',NULL,1,1)",
                f"insert into knowledge_document values({i},2,{i})",
                f"insert into knowledge_document_version values({i},{i},{i},{int(i != 4)},1)",
                f"insert into knowledgefile values({i},1,2,1,'file{i}')",
            ):
                await c.execute(text(stmt))

    @asynccontextmanager
    async def session():
        async with AsyncSession(db) as s:
            yield s

    calls = []
    relations = {"tag": {"R1", "R2", "R3", "R4"}}
    visible = {1, 3, 4}

    async def check(space, ids):
        assert space == 2
        return visible & set(ids)

    async def associated(tags):
        return TagAssociations({tag: relations[tag].copy() for tag in tags}, 1, True)

    async def filter_metadata(predicate):
        assert predicate == MetadataPredicate("year", "eq", 2026)
        return {"R1", "R2", "R4"}

    def handle(req):
        assert req.url.path == "/api/v1/knowledge-bases/kb/hybrid-search"
        calls.append(json.loads(req.content))
        # Retag during recall, and return an out-of-scope hit.
        relations["tag"].discard("R3")
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "knowledge_base_id": "kb",
                        "id": "c" + str(i),
                        "knowledge_id": "R" + str(i),
                        "content": "chunk" + str(i),
                    }
                    for i in (3, 2, 1, 4)
                ],
            },
        )

    token = current_tenant_id.set(1)
    try:
        async with httpx.AsyncClient(
            base_url="https://example.test/api/v1/", transport=httpx.MockTransport(handle)
        ) as client:

            def port(route):
                return WeKnoraSearchPort(client, route, associated, {("year", "eq"): int}, filter_metadata)

            service = ProviderRetrieval(port, repository=ProviderRetrievalRepository(session))
            engine = RetrievalEngine(SimpleNamespace(user_id=17), provider_retrieval=service)
            engine._knowledge_file_visibility_service = SimpleNamespace(post_filter_visible_files=check)
            yield engine, SimpleNamespace(id=2, type=3, tenant_id=1), calls, relations
    finally:
        current_tenant_id.reset(token)
        await db.dispose()


async def retrieve(case, selection):
    engine, space, _, _ = case
    return await engine.retrieve_many([space], query="q", max_content=1024, selections={2: selection})


async def test_actual_allowlist_and_recheck(case):
    hits = await retrieve(case, RetrievalSelection(tag_ref_ids=(8,)))
    assert [h.metadata["document_id"] for _, h in hits] == [1]
    assert case[2] == [{"query_text": "q", "knowledge_ids": ["R1", "R3"], "skip_context_enrichment": True}]


async def test_declared_metadata_is_intersected(case):
    await retrieve(case, RetrievalSelection(metadata=(MetadataPredicate("year", "eq", 2026),)))
    assert case[2][0]["knowledge_ids"] == ["R1"]
    for predicate in [MetadataPredicate("year", "eq", True), MetadataPredicate("year", "gt", 1)]:
        with pytest.raises(ValueError):
            await retrieve(case, RetrievalSelection(metadata=(predicate,)))
    assert len(case[2]) == 1


async def test_empty_stale_and_relation_failure_never_search(case):
    assert not await retrieve(case, RetrievalSelection(file_ids=()))
    with pytest.raises(ValueError):
        await retrieve(case, RetrievalSelection(tag_ref_ids=(9,)))
    case[3].clear()
    with pytest.raises(KeyError):
        await retrieve(case, RetrievalSelection(tag_ref_ids=(8,)))
    assert case[2] == []


async def test_mixed_sources_merge_by_position_not_provider_score(case, monkeypatch):
    from langchain_core.documents import Document

    engine, space, _, _ = case
    native = SimpleNamespace(id=7, type=0, model="native")

    async def native_hits(targets, **kwargs):
        assert targets == [native]
        return [(7, Document(page_content=content, metadata={"score": 999})) for content in ("native1", "native2")]

    monkeypatch.setattr(engine, "_retrieve_native_many", native_hits)
    hits = await engine.retrieve_many([native, space], query="q", max_content=1024)
    assert [(k, d.page_content) for k, d in hits] == [(7, "native1"), (2, "chunk3"), (7, "native2"), (2, "chunk1")]


async def test_revocation_and_stale_binding_fail_closed(case):
    engine, _, calls, _ = case
    visibility = engine._knowledge_file_visibility_service
    previous = visibility.post_filter_visible_files

    async def revoke(space_id, ids):
        if calls:
            return set()
        return await previous(space_id, ids)

    visibility.post_filter_visible_files = revoke
    assert not await retrieve(case, RetrievalSelection())
    async with engine.provider_retrieval.repository.session() as session:
        await session.execute(text("update knowledge_provider_generation set provider_instance_id=99"))
        await session.commit()
    with pytest.raises(ValueError, match="instance unavailable"):
        await retrieve(case, RetrievalSelection())
    assert len(calls) == 1


async def test_incomplete_snapshot_cannot_be_treated_as_empty(case):
    engine, space, calls, _ = case
    service = engine.provider_retrieval
    port = service.port_factory(await service.route(space))

    async def incomplete(tags):
        return TagAssociations({tags[0]: set()}, 2, False)

    port.associated = incomplete
    service.port_factory = lambda route: port
    with pytest.raises(ValueError, match="incomplete"):
        await retrieve(case, RetrievalSelection(tag_ref_ids=(8,)))
    token = current_tenant_id.set(17)
    try:
        with pytest.raises(ValueError, match="tenant"):
            await retrieve(case, RetrievalSelection())
    finally:
        current_tenant_id.reset(token)
    assert not calls


async def test_explicit_external_selection_without_port_never_reaches_native(monkeypatch):
    engine = RetrievalEngine(SimpleNamespace(user_id=17))
    target = SimpleNamespace(id=2, type=3)

    def no_native(*args, **kwargs):
        pytest.fail("external selection reached native retrieval")

    monkeypatch.setattr(engine, "_retrieve_native_many", no_native)
    monkeypatch.setattr(engine, "_visibility_service", no_native)
    with pytest.raises(ValueError, match="not configured"):
        await engine.retrieve_many([target], query="q", max_content=100, selections={2: RetrievalSelection()})
    target.provider_key = "weknora"
    with pytest.raises(ValueError, match="not configured"):
        await engine.retrieve_many([target], query="q", max_content=100)
    with pytest.raises(ValueError, match="not configured"):
        await engine.retrieve_and_filter(space=target, query="q", candidate_file_ids=None, max_content=100)
    with pytest.raises(ValueError, match="not configured"):
        await engine.retrieve_space(target, query="q", tag_names=["tag"], max_content=100)

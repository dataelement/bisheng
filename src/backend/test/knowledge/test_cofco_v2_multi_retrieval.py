"""COFCO's direct chat-service retrieval must rank globally and keep F046 hooks."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.services import knowledge_space_chat_service as module
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool


class RecallStore(VectorStore):
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    async def asimilarity_search_with_relevance_scores(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return self.rows[: kwargs.get("k", len(self.rows))]

    async def asimilarity_search(self, query, k=4, **kwargs):
        return [doc for doc, _ in await self.asimilarity_search_with_relevance_scores(query, k=k, **kwargs)]

    def similarity_search(self, query, k=4, **kwargs):
        return [doc for doc, _ in self.rows[:k]]

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError


def chunk(text, file_id, score):
    return Document(
        page_content=text, metadata={"document_id": file_id, "document_name": "new.pdf", "chunk_index": 0}
    ), score


@pytest.fixture
def retrieval(monkeypatch):
    service = KnowledgeSpaceChatService(MagicMock(), MagicMock(user_id=42, tenant_id=3))
    service._require_space_view_permission = AsyncMock()
    service._qa_filter_conf = lambda: SimpleNamespace(retrieval_initial_multiplier=1, retrieval_expansion_multiplier=2)
    rows, stores, allowed = {}, {}, {}
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        side_effect=lambda kb_id, file_ids: IndexFilter(
            strategy="in",
            accessible_size=1,
            milvus_expr=f"document_id in {file_ids or [kb_id * 10]}",
            es_filter=[{"terms": {"metadata.document_id": file_ids or [kb_id * 10]}}],
        )
    )
    visibility.project_mutation_retrieval_query = AsyncMock(
        side_effect=lambda *, space_id, query: f"{query}:{space_id}"
    )
    visibility.project_mutation_retrieval_names = AsyncMock(side_effect=lambda *, space_id, documents: documents)
    visibility.post_filter_retrievable_files = AsyncMock(
        side_effect=lambda kb_id, ids: set(ids) & allowed.get(kb_id, set(ids))
    )
    service._visibility_service = lambda: visibility
    service._resolve_kb_target_file_ids = AsyncMock(return_value=None)
    service._resolve_kb_file_ids_by_tags = AsyncMock(return_value=None)
    monkeypatch.setattr(module.KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=lambda kb_id: rows.get(kb_id)))
    monkeypatch.setattr(
        module.KnowledgeRag,
        "init_knowledge_milvus_vectorstore",
        AsyncMock(side_effect=lambda user_id, *, knowledge: stores[knowledge.id][0]),
    )
    monkeypatch.setattr(
        module.KnowledgeRag,
        "init_knowledge_es_vectorstore",
        AsyncMock(side_effect=lambda *, knowledge: stores[knowledge.id][1]),
    )
    use = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeService.permission_service.ensure_knowledge_use_async",
        use,
    )
    monkeypatch.setattr(
        module.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=10, update_time=datetime(2026, 11, 19, 12)),
                SimpleNamespace(id=20, update_time=datetime(2026, 11, 19, 13)),
            ]
        ),
    )

    def add(kb_id, vector, keyword=None, kind=3):
        rows[kb_id] = SimpleNamespace(id=kb_id, type=kind, user_id=7)
        stores[kb_id] = (RecallStore(vector), RecallStore(vector if keyword is None else keyword))

    add(1, [chunk("weak", 10, 0.1)])
    add(2, [chunk("strong", 20, 0.95)], kind=0)
    return SimpleNamespace(
        service=service, add=add, rows=rows, stores=stores, visibility=visibility, allowed=allowed, use=use
    )


@pytest.mark.parametrize("ids", [[1, 2], [2, 1]])
async def test_later_library_can_win_top_k_independent_of_id_order(retrieval, ids):
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=ids, top_k=1)
    assert [(kb, doc.page_content) for kb, doc in result] == [(2, "strong")]
    assert result[0][1].metadata["document_update_time"] == "2026-11-19 13:00:00"


async def test_same_multi_retriever_and_rrf_order_as_workflow(retrieval):
    retrieval.add(1, [chunk("A", 10, 0.99)], [chunk("A", 10, 0.1)])
    retrieval.add(2, [chunk("B", 20, 0.9)], [chunk("B", 20, 0.95)])
    retrieval.add(3, [chunk("C", 30, 0.8)], [chunk("C", 30, 0.9)])
    expected = await KnowledgeRetrieverTool(
        vector_retriever=MultiRetriever(vectors=[retrieval.stores[i][0] for i in (1, 2, 3)], search_kwargs=[{}] * 3),
        elastic_retriever=MultiRetriever(vectors=[retrieval.stores[i][1] for i in (1, 2, 3)], search_kwargs=[{}] * 3),
    ).ainvoke("q")
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2, 3])
    assert [doc.page_content for _, doc in result] == [doc.page_content for doc in expected]
    assert result[0][0] == 2


async def test_cofco_query_and_name_projection_are_applied_per_library(retrieval):
    async def old_view(*, space_id, documents):
        for doc in documents:
            doc.metadata["document_name"] = f"old-{space_id}.pdf"
            doc.page_content = doc.page_content.replace("new.pdf", f"old-{space_id}.pdf")
        return documents

    retrieval.add(2, [chunk("strong new.pdf", 20, 0.95)], kind=0)
    retrieval.visibility.project_mutation_retrieval_names.side_effect = old_view
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2], top_k=1)
    assert result[0][1].page_content == "strong old-2.pdf"
    assert result[0][1].metadata["document_name"] == "old-2.pdf"
    for kb_id, stores in retrieval.stores.items():
        assert all(store.queries[0][0] == f"q:{kb_id}" for store in stores)
    # Projection must not rewrite cached/shared native candidates in place.
    assert retrieval.stores[2][0].rows[0][0].page_content == "strong new.pdf"


async def test_approval_or_version_denied_hits_do_not_occupy_top_k(retrieval):
    retrieval.add(1, [chunk("unpublished", 11, 1.0), chunk("allowed", 10, 0.1)])
    retrieval.allowed[1] = {10}
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2], top_k=1)
    assert [(kb, doc.page_content) for kb, doc in result] == [(2, "strong")]
    retrieval.visibility.post_filter_retrievable_files.assert_any_await(1, {10, 11})


async def test_filter_and_projection_database_operations_do_not_overlap(retrieval):
    busy = False

    async def permit(kb_id, ids):
        nonlocal busy
        assert not busy
        busy = True
        try:
            await asyncio.sleep(0)
            return set(ids)
        finally:
            busy = False

    retrieval.visibility.post_filter_retrievable_files.side_effect = permit
    assert len(await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])) == 2


async def test_empty_library_expands_once_without_recalling_other_library(retrieval):
    retrieval.add(1, [*[chunk(f"stale-{i}", 11, 1.0) for i in range(100)], chunk("expanded", 10, 0.1)])
    retrieval.allowed[1] = {10}
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])
    assert {doc.page_content for _, doc in result} == {"expanded", "strong"}
    assert [kwargs["k"] for _, kwargs in retrieval.stores[1][0].queries] == [100, 200]
    assert len(retrieval.stores[2][0].queries) == 1


async def test_each_library_retains_its_own_content_budget(retrieval):
    retrieval.add(1, [chunk("A" * 6, 10, 0.99), chunk("B" * 6, 10, 0.98), chunk("C" * 6, 10, 0.97)])
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2], max_content=6)
    assert [(kb, doc.page_content) for kb, doc in result] == [(1, "A" * 6), (1, "B" * 6), (2, "strong")]


async def test_library_and_space_tag_resolvers_and_prefilters_are_preserved(retrieval):
    retrieval.service._resolve_kb_target_file_ids.return_value = [10]
    retrieval.service._resolve_kb_file_ids_by_tags.return_value = [20]
    await retrieval.service.aretrieve_chunks(
        query="q", knowledge_base_ids=[1, 2], kb_filters={1: {"tags": ["space-tag"]}, 2: {"tags": ["library-tag"]}}
    )
    retrieval.service._resolve_kb_target_file_ids.assert_awaited_once_with(1, ["space-tag"])
    retrieval.service._resolve_kb_file_ids_by_tags.assert_awaited_once_with(2, ["library-tag"])
    assert retrieval.stores[2][0].queries[0][1]["expr"] == "document_id in [20]"
    assert retrieval.stores[1][1].queries[0][1]["filter"] == [{"terms": {"metadata.document_id": [10]}}]


async def test_missing_tag_skips_only_its_library(retrieval):
    retrieval.service._resolve_kb_target_file_ids.return_value = []
    result = await retrieval.service.aretrieve_chunks(
        query="q", knowledge_base_ids=[1, 2], kb_filters={1: {"tags": ["missing"]}}
    )
    assert [(kb, doc.page_content) for kb, doc in result] == [(2, "strong")]
    assert retrieval.stores[1][0].queries == []


async def test_unsupported_type_is_rejected_even_after_another_library_has_hits(retrieval):
    retrieval.rows[2].type = 1
    with pytest.raises(KnowledgeTypeNotSupportedError):
        await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2], top_k=1)


async def test_permission_failure_does_not_return_partial_hits(retrieval):
    retrieval.visibility.post_filter_retrievable_files.side_effect = PermissionServiceUnavailableError()
    with pytest.raises(PermissionServiceUnavailableError):
        await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])


async def test_single_library_preserves_dispatch_and_projection(retrieval):
    result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1], top_k=1)
    assert [(kb, doc.page_content) for kb, doc in result] == [(1, "weak")]
    assert retrieval.stores[1][0].queries[0][0] == "q:1"


async def test_real_cofco_old_name_projection_runs_before_global_fusion(retrieval):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService

    actual = KnowledgeFileVisibilityService(MagicMock(), retrieval.service.login_user)
    projection = SimpleNamespace(name_projection=AsyncMock(return_value={20: ("old.pdf", "new.pdf")}))
    actual._mutation_read_projection = lambda: projection
    retrieval.visibility.project_mutation_retrieval_names = actual.project_mutation_retrieval_names
    retrieval.add(2, [chunk("strong new.pdf", 20, 0.95)], kind=0)
    token = set_current_tenant_id(3)
    try:
        result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2], top_k=1)
    finally:
        current_tenant_id.reset(token)
    assert result[0][1].page_content == "strong old.pdf"
    assert result[0][1].metadata["document_name"] == "old.pdf"
    assert retrieval.stores[2][0].rows[0][0].metadata["document_name"] == "new.pdf"


async def test_native_error_cancels_other_library_search(retrieval):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def fail(query, **kwargs):
        await started.wait()
        raise RuntimeError("index unavailable")

    async def pending(query, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    retrieval.stores[1][0].asimilarity_search_with_relevance_scores = fail
    retrieval.stores[2][0].asimilarity_search_with_relevance_scores = pending
    with pytest.raises(RuntimeError, match="index unavailable"):
        await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])
    assert stopped.is_set()


async def test_v2_endpoint_uses_cofco_operator_and_returns_global_top_k(retrieval, monkeypatch):
    from bisheng.open_endpoints.api.endpoints import filelib
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq

    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=retrieval.service.login_user))

    def chat_service(*, request, login_user):
        assert login_user is retrieval.service.login_user
        return retrieval.service

    monkeypatch.setattr(filelib, "KnowledgeSpaceChatService", chat_service)
    response = await filelib.retrieve_chunks(
        request=MagicMock(), req=RetrieveReq(query="q", knowledge_base_ids=[1, 2], top_k=1), version_repo=MagicMock()
    )
    assert response.status_code == 200
    assert [(item.knowledge_id, item.content) for item in response.data.chunks] == [(2, "strong")]
    assert response.data.chunks[0].document_update_time == "2026-11-19 13:00:00"


async def test_v2_keeps_cofco_permission_outage_mapping(retrieval, monkeypatch):
    from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
    from bisheng.open_endpoints.api.endpoints import filelib
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq

    monkeypatch.setattr(filelib, "get_open_api_operator_async", AsyncMock(return_value=retrieval.service.login_user))
    monkeypatch.setattr(filelib, "KnowledgeSpaceChatService", lambda **kwargs: retrieval.service)
    retrieval.visibility.post_filter_retrievable_files.side_effect = PermissionServiceUnavailableError()
    with pytest.raises(OpenApiAuthDependencyUnavailableError) as exc:
        await filelib.retrieve_chunks(
            request=MagicMock(), req=RetrieveReq(query="q", knowledge_base_ids=[1, 2]), version_repo=MagicMock()
        )
    assert exc.value.http_status == 503


async def test_empty_prefilters_skip_both_indexes(retrieval):
    retrieval.visibility.build_index_prefilter.side_effect = None
    retrieval.visibility.build_index_prefilter.return_value = IndexFilter(strategy="empty")
    assert await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2]) == []
    assert all(not store.queries for stores in retrieval.stores.values() for store in stores)


async def test_multi_search_keeps_the_service_account_permission_actor(retrieval):
    from bisheng.permission.application.identity import (
        get_current_permission_actor,
        reset_current_permission_actor,
        set_current_permission_actor,
    )
    from bisheng.permission.domain.services.permission_action_service import PermissionActor

    actor = PermissionActor(subject_type="service_account", subject_id=7, tenant_id=3)
    observed = []
    for stores in retrieval.stores.values():
        for store in stores:
            native = store.asimilarity_search_with_relevance_scores

            async def search(query, _native=native, **kwargs):
                observed.append(get_current_permission_actor())
                return await _native(query, **kwargs)

            store.asimilarity_search_with_relevance_scores = search
    token = set_current_permission_actor(actor)
    try:
        result = await retrieval.service.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])
    finally:
        reset_current_permission_actor(token)
    assert len(result) == 2 and len(observed) == 4
    assert all(value is actor for value in observed)

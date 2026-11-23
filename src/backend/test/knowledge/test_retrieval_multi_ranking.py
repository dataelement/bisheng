"""Exercise real MultiRetriever + RRF through the open retrieval engine/facade."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalRequest
from bisheng.knowledge.domain.services import retrieval_engine as engine_mod
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine
from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from test.knowledge.test_retrieval_facade import service_account_identity


class ScoreStore(VectorStore):
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def asimilarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        return self.rows[: kwargs.get("k", len(self.rows))]

    async def asimilarity_search(self, query, k=4, **kwargs):
        return [doc for doc, _ in await self.asimilarity_search_with_relevance_scores(query, k=k, **kwargs)]

    def similarity_search(self, query, k=4, **kwargs):
        return [doc for doc, _ in self.rows[:k]]

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError


def hit(content, file_id, score, *, chunk_index=0):
    return (
        Document(
            page_content=content,
            metadata={"document_id": file_id, "document_name": f"{file_id}.pdf", "chunk_index": chunk_index},
        ),
        score,
    )


@pytest.fixture
def retrieval(monkeypatch):
    stores = {}
    permitted = {}
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        side_effect=lambda kb_id, file_ids: IndexFilter(
            strategy="in",
            milvus_expr=f"document_id in {file_ids or [kb_id * 10]}",
            es_filter=[{"terms": {"metadata.document_id": file_ids or [kb_id * 10]}}],
            accessible_size=1,
        )
    )
    active_filter = False

    async def post_filter(kb_id, file_ids):
        nonlocal active_filter
        assert not active_filter, "the request-scoped DB session must not be used concurrently"
        active_filter = True
        try:
            await asyncio.sleep(0)
            return set(file_ids) & permitted.get(kb_id, set(file_ids))
        finally:
            active_filter = False

    visibility.post_filter_retrievable_files = AsyncMock(side_effect=post_filter)
    monkeypatch.setattr(RetrievalEngine, "_visibility_service", lambda self: visibility)
    monkeypatch.setattr(
        RetrievalEngine,
        "_qa_filter_conf",
        lambda self: SimpleNamespace(retrieval_initial_multiplier=1, retrieval_expansion_multiplier=2),
    )
    monkeypatch.setattr(
        engine_mod.KnowledgeRag,
        "init_knowledge_milvus_vectorstore",
        AsyncMock(side_effect=lambda _user_id, *, knowledge, **kwargs: stores[knowledge.id][0]),
    )
    monkeypatch.setattr(
        engine_mod.KnowledgeRag,
        "init_knowledge_es_vectorstore",
        AsyncMock(side_effect=lambda *, knowledge, **kwargs: stores[knowledge.id][1]),
    )
    ensure_use = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeService.permission_service.ensure_knowledge_use_async",
        ensure_use,
    )
    monkeypatch.setattr(engine_mod.KnowledgeFileDao, "aget_file_by_ids", AsyncMock(return_value=[]))
    engine = RetrievalEngine(service_account_identity().login_user)

    def add(kb_id, vector_rows, keyword_rows=None, *, knowledge_type=KnowledgeTypeEnum.SPACE.value):
        stores[kb_id] = (ScoreStore(vector_rows), ScoreStore(keyword_rows if keyword_rows is not None else vector_rows))
        return SimpleNamespace(id=kb_id, type=knowledge_type, user_id=7)

    return SimpleNamespace(
        engine=engine, add=add, stores=stores, visibility=visibility, permitted=permitted, ensure_use=ensure_use
    )


@pytest.mark.parametrize("order", [[1, 2], [2, 1]])
async def test_v2_facade_top_k_uses_global_ranking(retrieval, knowledge_rows, fake_visibility, order):
    """A later, more relevant library must win top_k=1 in either request order."""
    retrieval.add(1, [hit("weak", 10, 0.1)])
    retrieval.add(2, [hit("strong", 20, 0.95)], knowledge_type=KnowledgeTypeEnum.NORMAL.value)
    knowledge_rows(1, KnowledgeTypeEnum.SPACE.value)
    knowledge_rows(2, KnowledgeTypeEnum.NORMAL.value)
    fake_visibility.granted["knowledge_space"] = {1}
    fake_visibility.granted["knowledge_library"] = {2}

    result = await RetrievalFacadeService.retrieve(
        service_account_identity(), RetrievalRequest(query="q", knowledge_ids=order, top_k=1)
    )

    assert [(chunk.knowledge_id, chunk.content) for chunk in result.chunks] == [(2, "strong")]
    assert result.chunks[0].document_id == 20
    assert result.chunks[0].document_update_time == ""
    assert result.total == 1
    assert retrieval.ensure_use.await_count == 1
    for stores in retrieval.stores.values():
        assert [len(store.calls) for store in stores] == [1, 1]


async def test_fusion_matches_existing_workflow_multi_retriever(retrieval):
    a = retrieval.add(1, [hit("A", 10, 0.99)], [hit("A", 10, 0.1)])
    b = retrieval.add(2, [hit("B", 20, 0.9)], [hit("B", 20, 0.95)])
    c = retrieval.add(3, [hit("C", 30, 0.8)], [hit("C", 30, 0.9)])
    expected = await KnowledgeRetrieverTool(
        vector_retriever=MultiRetriever(vectors=[retrieval.stores[i][0] for i in (1, 2, 3)], search_kwargs=[{}] * 3),
        elastic_retriever=MultiRetriever(vectors=[retrieval.stores[i][1] for i in (1, 2, 3)], search_kwargs=[{}] * 3),
        max_content=15000,
    ).ainvoke("q")

    result = await retrieval.engine.retrieve_many([a, b, c], query="q", max_content=15000)

    assert [doc.page_content for _, doc in result] == [doc.page_content for doc in expected]
    assert result[0][0] == 2  # B wins the fused ranks despite A's higher vector score.
    assert {kb_id for kb_id, _ in result} == {1, 2, 3}
    assert all("knowledge_id" not in doc.metadata for stores in retrieval.stores.values() for doc, _ in stores[0].rows)


async def test_hidden_or_stale_hits_are_removed_before_fusion(retrieval):
    a = retrieval.add(1, [hit("hidden", 11, 1.0), hit("allowed", 10, 0.2)])
    b = retrieval.add(2, [hit("strong", 20, 0.9)])
    retrieval.permitted[1] = {10}

    result = await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000)

    assert [(kb_id, doc.page_content) for kb_id, doc in result] == [(2, "strong"), (1, "allowed")]
    assert retrieval.visibility.post_filter_retrievable_files.await_count == 2


async def test_empty_filtered_library_expands_without_recalling_successful_library(retrieval):
    initial = [hit(f"stale-{i}", 11, 1.0 - i / 1000) for i in range(100)]
    a = retrieval.add(1, [*initial, hit("expanded", 10, 0.1)])
    b = retrieval.add(2, [hit("strong", 20, 0.9)])
    retrieval.permitted[1] = {10}

    result = await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000)

    assert {doc.page_content for _, doc in result} == {"expanded", "strong"}
    assert [call["k"] for call in retrieval.stores[1][0].calls] == [100, 200]
    assert [call["k"] for call in retrieval.stores[2][0].calls] == [100]


async def test_max_content_stays_per_library_after_global_fusion(retrieval):
    a = retrieval.add(1, [hit("A" * 6, 10, 0.99), hit("B" * 6, 10, 0.98), hit("C" * 6, 10, 0.97)])
    b = retrieval.add(2, [hit("D" * 6, 20, 0.5)])

    result = await retrieval.engine.retrieve_many([a, b], query="q", max_content=6)

    # Preserve the existing whole-chunk cutoff (the chunk crossing the cap is
    # included), but exhausting KB 1 must not consume KB 2's content budget.
    assert [(kb_id, doc.page_content) for kb_id, doc in result] == [(1, "A" * 6), (1, "B" * 6), (2, "D" * 6)]


async def test_tag_filters_are_preserved_on_both_native_channels(retrieval):
    a = retrieval.add(1, [hit("tagged", 10, 0.9)])
    b = retrieval.add(2, [hit("other", 20, 0.5)])
    resolve = AsyncMock(side_effect=lambda kb_id, names: [10] if names else None)
    retrieval.engine.resolve_space_file_ids_by_tags = resolve

    await retrieval.engine.retrieve_many([a, b], query="q", tag_filters={1: ["tag"]}, max_content=15000)

    resolve.assert_any_await(1, ["tag"])
    assert retrieval.stores[1][0].calls[0]["expr"] == "document_id in [10]"
    assert retrieval.stores[1][1].calls[0]["filter"] == [{"terms": {"metadata.document_id": [10]}}]


async def test_empty_tag_match_skips_only_that_library(retrieval):
    a = retrieval.add(1, [hit("excluded", 10, 0.99)])
    b = retrieval.add(2, [hit("included", 20, 0.5)])
    retrieval.engine.resolve_space_file_ids_by_tags = AsyncMock(return_value=[])

    result = await retrieval.engine.retrieve_many([a, b], query="q", tag_filters={1: ["missing"]}, max_content=15000)

    assert [(kb_id, doc.page_content) for kb_id, doc in result] == [(2, "included")]
    assert retrieval.stores[1][0].calls == []


async def test_permission_outage_does_not_return_other_library_hits(retrieval):
    a = retrieval.add(1, [hit("first", 10, 0.99)])
    b = retrieval.add(2, [hit("second", 20, 0.5)])
    retrieval.visibility.post_filter_retrievable_files.side_effect = PermissionServiceUnavailableError()

    with pytest.raises(PermissionServiceUnavailableError):
        await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000)


async def test_library_denial_is_checked_before_search(retrieval):
    a = retrieval.add(1, [hit("first", 10, 0.99)])
    b = retrieval.add(2, [hit("second", 20, 0.5)], knowledge_type=KnowledgeTypeEnum.NORMAL.value)
    retrieval.ensure_use.side_effect = PermissionServiceUnavailableError()

    with pytest.raises(PermissionServiceUnavailableError):
        await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000)
    assert all(not store.calls for stores in retrieval.stores.values() for store in stores)


async def test_no_targets_returns_empty(retrieval):
    assert await retrieval.engine.retrieve_many([], query="q", max_content=15000) == []


async def test_single_library_keeps_existing_retrieval_path(retrieval):
    a = retrieval.add(1, [hit("single", 10, 0.9)])
    result = await retrieval.engine.retrieve_many([a], query="q", max_content=15000)
    assert [(kb_id, doc.page_content) for kb_id, doc in result] == [(1, "single")]


async def test_v2_endpoint_returns_globally_ranked_top_k(retrieval, knowledge_rows, fake_visibility, monkeypatch):
    from bisheng.open_endpoints.api.endpoints import filelib
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq
    from test.knowledge.test_retrieval_facade_equality import _principal

    retrieval.add(1, [hit("weak", 10, 0.1)])
    retrieval.add(2, [hit("strong", 20, 0.95)])
    knowledge_rows(1, KnowledgeTypeEnum.SPACE.value)
    knowledge_rows(2, KnowledgeTypeEnum.SPACE.value)
    fake_visibility.granted["knowledge_space"] = {1, 2}
    monkeypatch.setattr(filelib, "get_current_open_api_principal", _principal)

    result = await filelib.retrieve_chunks(
        request=MagicMock(), req=RetrieveReq(query="q", knowledge_base_ids=[1, 2], top_k=1), version_repo=MagicMock()
    )

    assert result.status_code == 200
    assert [(chunk.knowledge_id, chunk.content) for chunk in result.data.chunks] == [(2, "strong")]
    assert result.data.total == 1


async def test_native_search_error_cancels_sibling_retrieval(retrieval):
    a = retrieval.add(1, [hit("first", 10, 0.9)])
    b = retrieval.add(2, [hit("second", 20, 0.8)])
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fail(query, **kwargs):
        await started.wait()
        raise RuntimeError("search unavailable")

    async def slow(query, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    retrieval.stores[1][0].asimilarity_search_with_relevance_scores = fail
    retrieval.stores[2][0].asimilarity_search_with_relevance_scores = slow
    with pytest.raises(RuntimeError, match="search unavailable"):
        await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000)
    assert cancelled.is_set()


async def test_all_empty_prefilters_skip_search(retrieval):
    a = retrieval.add(1, [hit("first", 10, 0.9)])
    b = retrieval.add(2, [hit("second", 20, 0.8)])
    retrieval.visibility.build_index_prefilter.side_effect = None
    retrieval.visibility.build_index_prefilter.return_value = IndexFilter(strategy="empty")

    assert await retrieval.engine.retrieve_many([a, b], query="q", max_content=15000) == []
    assert all(not store.calls for stores in retrieval.stores.values() for store in stores)


async def test_multi_search_preserves_execution_identity(retrieval, knowledge_rows, fake_visibility):
    from bisheng.open_api.domain.context import (
        get_current_open_api_principal,
        reset_current_open_api_principal,
        set_current_open_api_principal,
    )
    from bisheng.permission.application.identity import get_current_permission_actor
    from test.knowledge.test_retrieval_facade_equality import _principal

    retrieval.add(1, [hit("weak", 10, 0.1)])
    retrieval.add(2, [hit("strong", 20, 0.95)])
    for kb_id in (1, 2):
        knowledge_rows(kb_id, KnowledgeTypeEnum.SPACE.value)
    fake_visibility.granted["knowledge_space"] = {1, 2}
    identity, principal = service_account_identity(), _principal()
    calls = []

    for stores in retrieval.stores.values():
        for store in stores:
            native = store.asimilarity_search_with_relevance_scores

            async def search(query, _native=native, **kwargs):
                assert get_current_permission_actor() is identity.actor
                assert get_current_open_api_principal() is principal
                calls.append(True)
                return await _native(query, **kwargs)

            store.asimilarity_search_with_relevance_scores = search

    token = set_current_open_api_principal(principal)
    try:
        result = await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query="q", knowledge_ids=[1, 2]))
    finally:
        reset_current_open_api_principal(token)

    assert len(result.chunks) == 2 and len(calls) == 4
    for builder in (
        engine_mod.KnowledgeRag.init_knowledge_milvus_vectorstore,
        engine_mod.KnowledgeRag.init_knowledge_es_vectorstore,
    ):
        assert all(call.kwargs["login_user"] is identity.login_user for call in builder.await_args_list)

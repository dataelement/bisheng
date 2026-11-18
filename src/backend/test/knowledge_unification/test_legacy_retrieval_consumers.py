"""Old saved selectors dispatch by real Root type without rewriting their JSON."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core import database
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services import space_flow_retrieval as spaces
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    IndexFilter,
    KnowledgeFileVisibilityService,
)
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.workflow.common.knowledge import ConditionCases, RagUtils
from bisheng.workstation.domain.schemas.chat import UseKnowledgeBaseParam
from bisheng.workstation.domain.services import workstation_service as workstation
from test.knowledge_unification.test_kn_version_read_repository import (
    catalog as catalog,
)
from test.knowledge_unification.test_kn_version_read_repository import (
    chain,
    space,
)
from test.knowledge_unification.test_kn_version_read_repository import (
    concrete_tenant as concrete_tenant,
)


def doc(ident, root, text):
    return Document(
        page_content=text, metadata={"document_id": ident, "knowledge_id": root, "document_name": f"{ident}.md"}
    )


class Store(VectorStore):
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append(dict(kwargs))
        return list(self.rows)

    async def asimilarity_search_with_relevance_scores(self, query, **kwargs):
        return self.similarity_search_with_relevance_scores(query, **kwargs)

    def similarity_search(self, query, k=4, **kwargs):
        return [row for row, score in self.similarity_search_with_relevance_scores(query, k=k, **kwargs)]

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise AssertionError("native query adapter must not construct embeddings")


@pytest.fixture
async def roots(catalog, monkeypatch):
    normal, qa = space(20), space(30)
    normal.type, qa.type = 0, 1
    actual = [space(), normal, qa, *chain(1, 2), *chain(2, space_id=20), *chain(3, space_id=30)]
    await catalog.seed(actual)
    monkeypatch.setattr(database, "get_async_db_session", catalog.sessions)
    monkeypatch.setattr("bisheng.knowledge.domain.models.knowledge.get_async_db_session", catalog.sessions)
    monkeypatch.setattr(workstation, "get_async_db_session", catalog.sessions)
    monkeypatch.setattr(KnowledgeFileDao, "get_file_by_ids", lambda ids: [])
    user = UserPayload(user_id=42, tenant_id=101, user_name="runtime", user_role=[])
    build_user = AsyncMock(return_value=user)
    monkeypatch.setattr(spaces, "abuild_scoped_login_user", build_user)
    pre, post = [], []

    async def index(self, root, candidates):
        pre.append((root, self.login_user.user_id))
        return IndexFilter(
            strategy="in",
            milvus_expr="document_id in [10002]",
            es_filter=[{"terms": {"metadata.document_id": [10002]}}],
        )

    async def filtered(self, root, ids):
        post.append((root, self.login_user.user_id, set(ids)))
        return {10002} & set(ids)

    monkeypatch.setattr(KnowledgeFileVisibilityService, "build_index_prefilter", index)
    monkeypatch.setattr(KnowledgeFileVisibilityService, "post_filter_retrievable_files", filtered)
    return SimpleNamespace(catalog=catalog, user=user, build_user=build_user, pre=pre, post=post)


async def test_actual_migrated_root_in_legacy_org_bucket_uses_space_runtime_and_preserves_qa_normal(roots, monkeypatch):
    called = []

    async def visible(self, ident):
        called.append(ident)
        return True

    monkeypatch.setattr(KnowledgeFileVisibilityService, "is_space_visible", visible)
    permission = AsyncMock(return_value=[20, 30])
    monkeypatch.setattr(workstation.KnowledgePermissionService, "filter_knowledge_ids_by_action_async", permission)

    async def vectors(**kwargs):
        ident = kwargs["knowledge_ids"][0]
        return {
            ident: {
                "knowledge": SimpleNamespace(id=ident, name=f"root{ident}"),
                "milvus": Store([(doc(ident * 1000 + 1, ident, f"legacy{ident}"), 0.5)]),
                "es": None,
            }
        }

    vector_port = AsyncMock(side_effect=vectors)
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore", vector_port)
    migrated = AsyncMock(return_value=[doc(10002, 10, "space-success")])
    monkeypatch.setattr(spaces, "aretrieve_space_documents", migrated)
    selection = UseKnowledgeBaseParam(organization_knowledge_ids=[20, 10, 30])
    before = selection.model_dump_json()
    formatted, docs, failures = await workstation.WorkStationService.queryChunksFromDB("q", selection, 1234, roots.user)
    assert [row.page_content for row in docs] == ["legacy20", "space-success", "legacy30"]
    assert failures == [] and len(formatted) == 3
    assert selection.model_dump_json() == before
    assert called == [10]
    assert [call.kwargs["knowledge_ids"] for call in vector_port.await_args_list] == [[20], [30]]
    assert permission.await_args.args[1:] == ([20, 30], "use")
    assert migrated.await_args.kwargs["space_ids"] == [10]
    assert migrated.await_args.kwargs["identity_user"] is roots.user
    assert migrated.await_args.kwargs["max_content"] == 1234
    assert migrated.await_args.kwargs["retrieval_multipliers"] == (1,)


def node(roots, *, auth):
    value = object.__new__(RagUtils)
    value._knowledge_type, value._knowledge_value = "knowledge", ["10", "20", "30"]
    value._knowledge_auth, value.user_id, value.flow_user_id, value.tenant_id = auth, 42, 7, 101
    value.user_info = SimpleNamespace(user_name="runtime")
    value._knowledge_vector_list = []
    value._metadata_filter = ConditionCases(enabled=False)
    value._keyword_weight, value._vector_weight = 0.75, 0.25
    value._retriever_kwargs, value._max_chunk_size, value._rerank_model = {"k": 100, "param": {"ef": 110}}, 10, None
    value._multi_milvus_retriever = value._multi_es_retriever = None
    return value


@pytest.mark.parametrize("auth", [True, False])
async def test_workflow_old_selector_keeps_one_global_weighted_fusion_and_original_limit(roots, monkeypatch, auth):
    sources = {
        10: {
            "knowledge": space(),
            "milvus": Store(
                [(doc(10001, 10, "history"), 0.99), (doc(10003, 10, "orphan"), 0.98), (doc(10002, 10, "primary"), 0.7)]
            ),
            "es": Store([(doc(10003, 10, "orphan"), 1.0), (doc(10002, 10, "primary"), 0.8)]),
        },
        20: {
            "knowledge": space(20),
            "milvus": Store([(doc(20001, 20, "normal"), 0.9)]),
            "es": Store([(doc(20001, 20, "normal"), 0.5)]),
        },
        30: {
            "knowledge": space(30),
            "milvus": Store([(doc(30001, 30, "qa"), 0.6)]),
            "es": Store([(doc(30001, 30, "qa"), 0.9)]),
        },
    }
    sources[20]["knowledge"].type, sources[30]["knowledge"].type = 0, 1
    original = {key: dict(value) for key, value in sources.items()}
    port = Mock(return_value=sources)
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore_sync", port)
    value = node(roots, auth=auth)
    fetch = Mock(wraps=value._fetch_non_primary_file_ids)
    monkeypatch.setattr(value, "_fetch_non_primary_file_ids", fetch)
    calls = []
    fusion = KnowledgeRetrieverTool._rrf_rerank

    def counted(self, vector, elastic, question):
        calls.append((self.rrf_weights, self.max_content))
        return fusion(self, vector, elastic, question)

    monkeypatch.setattr(KnowledgeRetrieverTool, "_rrf_rerank", counted)
    await asyncio.to_thread(value.init_multi_retriever)
    assert fetch.call_args.args == ([20, 30],)
    actual = await asyncio.to_thread(value.retrieve_question, "q")
    assert calls == [([0.25, 0.75], 10)]
    assert all(row.metadata["document_id"] not in {10001, 10003} for row in actual)
    assert value._knowledge_value == ["10", "20", "30"]
    assert port.call_args.kwargs["invoke_user_id"] == 42 and port.call_args.kwargs["check_auth"] is auth
    if auth:
        roots.build_user.assert_awaited_once_with(42, 101)
        assert roots.pre == [(10, 42)] and roots.post
    else:
        roots.build_user.assert_not_awaited()
        assert roots.pre == roots.post == []
    assert all(sources[key][side] is original[key][side] for key in sources for side in ("milvus", "es"))
    # Same original native global pipeline with the invalid historical pair removed.
    clean_m = [
        Store(
            [(row, score) for row, score in entry["milvus"].rows if row.metadata["document_id"] not in {10001, 10003}]
        )
        for entry in sources.values()
    ]
    clean_e = [
        Store([(row, score) for row, score in entry["es"].rows if row.metadata["document_id"] not in {10001, 10003}])
        for entry in sources.values()
    ]
    expected = KnowledgeRetrieverTool(
        vector_retriever=MultiRetriever(
            vectors=clean_m, search_kwargs=[{"k": 100, "param": {"ef": 110}}] * 3, finally_k=100
        ),
        elastic_retriever=MultiRetriever(
            vectors=clean_e, search_kwargs=[{"k": 100, "param": {"ef": 110}}] * 3, finally_k=100
        ),
        max_content=10,
        rrf_weights=[0.25, 0.75],
        rrf_remove_zero_score=True,
        sort_by_source_and_index=True,
    )._run("q")
    assert [(row.page_content, row.metadata) for row in actual] == [
        (row.page_content, row.metadata) for row in expected
    ]


@pytest.mark.parametrize("auth", [True, False])
async def test_sync_and_async_native_store_scores_keep_global_cap_and_cannot_mutate_shared_kwargs(
    roots, monkeypatch, auth
):
    class MutatingStore(Store):
        def similarity_search_with_relevance_scores(self, query, **kwargs):
            if "param" in kwargs:
                kwargs["param"]["ef"] = 1
            return super().similarity_search_with_relevance_scores(query, **kwargs)

    stores = {
        10: {
            "knowledge": space(),
            "milvus": MutatingStore([(doc(10003, 10, "orphan"), 1.0), (doc(10002, 10, "primary"), 0.7)]),
            "es": None,
        },
        20: {"knowledge": space(20), "milvus": Store([(doc(20001, 20, "normal"), 0.9)]), "es": None},
    }
    stores[20]["knowledge"].type = 0
    port = Mock(return_value=stores)
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore_sync", port)
    value = node(roots, auth=auth)
    value._knowledge_value = ["10", "20"]
    await asyncio.to_thread(value.init_multi_retriever)
    sync = await asyncio.to_thread(value._multi_milvus_retriever.invoke, "q")
    asynchronous = await value._multi_milvus_retriever.ainvoke("q")
    assert [row.metadata["document_id"] for row in sync] == [20001, 10002]
    assert sync == asynchronous
    assert value._retriever_kwargs["param"] == {"ef": 110}
    assert value._multi_milvus_retriever.search_kwargs[0]["param"] == {"ef": 110}
    assert value._multi_milvus_retriever.vectors[1] is stores[20]["milvus"]
    assert not roots.pre and not roots.post if not auth else roots.post


@pytest.mark.parametrize("auth", [True, False])
async def test_metadata_no_match_never_becomes_unfiltered_space(roots, monkeypatch, auth):
    source = {10: {"knowledge": space(), "milvus": Store([(doc(10002, 10, "primary"), 1.0)]), "es": None}}
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore_sync", Mock(return_value=source))
    value = node(roots, auth=auth)
    value._knowledge_value = ["10"]
    value._metadata_filter = SimpleNamespace(get_knowledge_filter=lambda **kwargs: (None, None))
    await asyncio.to_thread(value.init_multi_retriever)
    assert await asyncio.to_thread(value.retrieve_question, "q") == []
    assert source[10]["milvus"].calls == []


@pytest.mark.parametrize("auth", [True, False])
@pytest.mark.parametrize("kind,tenant", [(2, 101), (9, 101), (3, 202)])
async def test_unknown_retired_and_foreign_root_never_enter_the_unchecked_legacy_space_branch(
    roots, monkeypatch, auth, kind, tenant
):
    invalid = space(90, tenant)
    invalid.type = kind
    await roots.catalog.seed([invalid])
    port = Mock(side_effect=AssertionError("unavailable Root must not initialize its store"))
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore_sync", port)
    value = node(roots, auth=auth)
    value._knowledge_value = ["90"]
    with pytest.raises(ValueError, match="unavailable"):
        await asyncio.to_thread(value.init_multi_retriever)
    port.assert_not_called()
    roots.build_user.assert_not_awaited()


async def test_actual_type_classification_is_scalar_bounded_and_keeps_c3(roots):
    from bisheng.knowledge.domain.repositories.retrieval_file_repository import KnowledgeRetrievalFileRepository

    await roots.catalog.seed([*[space(ident) for ident in range(100, 501)], space(901, 202)])
    roots.catalog.facts.sql.clear()
    async with roots.catalog.sessions() as session:
        result = await KnowledgeRetrievalFileRepository().aload_actual_types(
            session, knowledge_ids=[*range(100, 501), 901]
        )
    assert result == dict.fromkeys(range(100, 501), 3)
    statements = roots.catalog.facts.sql
    assert len(statements) == 3
    assert all(len(parameters) <= 201 for query, parameters in statements)
    assert all("metadata_fields" not in query and "collection_name" not in query for query, parameters in statements)


async def test_default_f029_attempts_remain_unchanged_while_actual_workstation_keeps_native_k100_once(
    roots, monkeypatch
):
    vector, elastic = Store([]), Store([])
    monkeypatch.setattr(workstation.KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock(return_value=vector))
    monkeypatch.setattr(workstation.KnowledgeRag, "init_knowledge_es_vectorstore", AsyncMock(return_value=elastic))
    monkeypatch.setattr(
        KnowledgeFileVisibilityService,
        "_config",
        lambda self: SimpleNamespace(
            retrieval_initial_multiplier=2,
            retrieval_expansion_multiplier=4,
        ),
    )
    assert (
        await spaces.aretrieve_space_documents(
            space_ids=[10],
            query="q",
            identity_user=roots.user,
            max_content=1000,
        )
        == []
    )
    assert [call["k"] for call in vector.calls] == [200, 400]
    assert [call["k"] for call in elastic.calls] == [200, 400]
    vector.calls.clear()
    elastic.calls.clear()
    monkeypatch.setattr(KnowledgeFileVisibilityService, "is_space_visible", AsyncMock(return_value=True))
    legacy = AsyncMock(side_effect=AssertionError("real Root3 must not enter old org vector path"))
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore", legacy)
    assert await workstation.WorkStationService.queryChunksFromDB(
        "q",
        UseKnowledgeBaseParam(organization_knowledge_ids=[10]),
        1000,
        roots.user,
    ) == ([], [], [])
    assert [call["k"] for call in vector.calls] == [100]
    assert vector.calls[0]["param"] == {"ef": 110}
    assert [call["k"] for call in elastic.calls] == [100]
    roots.build_user.assert_not_awaited()
    legacy.assert_not_awaited()


@pytest.mark.parametrize("threshold,strategy", [(2, "none"), (3, "in")])
async def test_off_large_positive_set_uses_original_threshold_none_and_still_rejects_stale_scores(
    roots, monkeypatch, threshold, strategy
):
    from bisheng.common.services.config_service import settings
    from bisheng.core.config.settings import KnowledgeQAFilterConf

    monkeypatch.setattr(settings, "knowledge_qa_filter", KnowledgeQAFilterConf(index_filter_threshold=threshold))
    await roots.catalog.seed([*chain(4), *chain(5)])
    store = Store(
        [(doc(10001, 10, "history"), 1.0), (doc(10003, 10, "orphan"), 0.99), (doc(10002, 10, "primary"), 0.7)]
    )
    sources = {10: {"knowledge": space(), "milvus": store, "es": None}}
    monkeypatch.setattr(workstation.KnowledgeRag, "get_multi_knowledge_vectorstore_sync", Mock(return_value=sources))
    value = node(roots, auth=False)
    value._knowledge_value = ["10"]
    await asyncio.to_thread(value.init_multi_retriever)
    index = value._legacy_space_filters[10]
    assert index.accessible_size == 3 and index.strategy == strategy
    if strategy == "none":
        assert index.milvus_expr is None and not index.es_filter
    else:
        assert index.es_filter == [{"terms": {"metadata.document_id": [10002, 40001, 50001]}}]
    result = await asyncio.to_thread(value._multi_milvus_retriever.invoke, "q")
    assert [row.metadata["document_id"] for row in result] == [10002]
    if strategy == "none":
        assert "expr" not in store.calls[0]
    roots.build_user.assert_not_awaited()
    assert roots.pre == roots.post == []

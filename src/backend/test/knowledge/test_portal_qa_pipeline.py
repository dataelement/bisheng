"""实际统一编排与 Resolver 的集成边界，外部存储和身份服务用可控替身。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf
from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan, QaRetrievalError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.services.portal_qa_retrieval_service import retrieve_portal_qa
from test.knowledge.test_knowledge_retrieval_scope_resolver import (
    StubFileRepository,
    StubDocumentRepository,
    StubVersionRepository,
    make_entry,
    make_document,
    hit,
)


@pytest.mark.parametrize("case", ["normal", "revoke", "favorite_removed", "es_init_failure", "embedding_failure"])
async def test_pipeline_authorizes_before_rerank_and_freshly_before_model(monkeypatch, case):
    from bisheng.core import database
    from bisheng.core.search.elasticsearch import manager
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
    from bisheng.knowledge.domain.repositories.implementations import (
        portal_search_context_repository_impl as context_repo,
        knowledge_file_repository_impl as files,
        knowledge_document_repository_impl as docs,
        knowledge_document_version_repository_impl as versions,
        department_file_view_grant_repository_impl as grants,
    )
    from bisheng.knowledge.domain.services import department_file_view_access_service as access
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.knowledge.rag import shared_space_storage as storage, async_retrieval_runtime as runtime
    from bisheng.llm.domain import LLMService

    # 项目测试启动过程可能为工作台依赖安装模块桩；复用既有测试的真实类加载入口。
    from test.workstation.test_portal_qa_knowledge_scope import workstation_service

    WorkStationService = workstation_service.WorkStationService

    sessions, closed, checks = [], [], []

    @asynccontextmanager
    async def session():
        value = len(sessions)
        sessions.append(value)
        try:
            yield value
        finally:
            closed.append(value)

    monkeypatch.setattr(database, "get_async_db_session", session)
    entry = make_entry(1, space_id=10, entry_type="manager")
    entry.status = KnowledgeFileStatus.SUCCESS.value
    monkeypatch.setattr(files, "KnowledgeFileRepositoryImpl", lambda session: StubFileRepository([entry]))
    from test.knowledge.test_portal_qa_context import ContextRepository

    data = {
        "documents": {91: make_document()},
        "entries": {91: [entry]},
        "spaces": {10: SimpleNamespace(id=10, tenant_id=7, type=KnowledgeTypeEnum.SPACE.value, user_id=8)},
        "scopes": {10: SimpleNamespace(tenant_id=7, level="department", owner_type="department", owner_id=20)},
        "bindings": {10: [SimpleNamespace(tenant_id=7, department_id=20)]},
        "departments": {20: SimpleNamespace(tenant_id=7, path="/20")},
    }
    monkeypatch.setattr(context_repo, "PortalSearchContextRepositoryImpl", lambda *args, **kw: ContextRepository(data))
    monkeypatch.setattr(
        docs, "KnowledgeDocumentRepositoryImpl", lambda session: StubDocumentRepository([make_document()])
    )
    monkeypatch.setattr(versions, "KnowledgeDocumentVersionRepositoryImpl", lambda session: StubVersionRepository([]))
    monkeypatch.setattr(grants, "DepartmentFileViewGrantRepositoryImpl", lambda session: object())

    async def permission_ids(self, login_user, files):
        phase = len(sessions) - 1
        checks.append((phase, [f.id for f in files]))
        allowed = not (case == "revoke" and phase == 1)
        return {f.id: {"view_file"} if allowed else set() for f in files}

    monkeypatch.setattr(access.DepartmentFileViewAccessService, "_resolve_permission_ids", permission_ids)
    monkeypatch.setattr(
        KnowledgeSpaceChatService,
        "_permission_service",
        lambda self: SimpleNamespace(
            _require_read_permission=AsyncMock(side_effect=AssertionError("no space permission preflight"))
        ),
    )
    monkeypatch.setattr(KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=list(data["spaces"].values())))
    monkeypatch.setattr(
        storage,
        "aresolve_space_shared_routing",
        AsyncMock(return_value=SimpleNamespace(shared_enabled=True, collection_name="shared-7", routing_version=1)),
    )
    monkeypatch.setattr(
        runtime,
        "get_async_retrieval_runtime",
        AsyncMock(return_value=SimpleNamespace(embed_query=AsyncMock(return_value=[0.1]))),
    )
    es_client = AsyncMock(return_value=object())
    if case == "es_init_failure":
        es_client.side_effect = RuntimeError("ES client initialization failed")
        monkeypatch.setattr(storage.SharedSpaceStorageReader, "_assert_readable", AsyncMock())
    monkeypatch.setattr(manager, "get_es_connection", es_client)
    embedding_model = AsyncMock(return_value=object())
    if case == "embedding_failure":
        embedding_model.side_effect = RuntimeError("embedding model unavailable")
    monkeypatch.setattr(LLMService, "aget_knowledge_default_embedding", embedding_model)
    dense = AsyncMock(return_value=[hit(), hit(chunk_index=1)])
    sparse = AsyncMock(return_value=[hit(), hit(chunk_index=1)] if case == "embedding_failure" else [])

    class Cursor:
        def __init__(self, search):
            self.search, self.used = search, False

        async def next_batch(self):
            if self.used:
                return []
            self.used = True
            return await self.search()

        async def close(self):
            pass

    dense_open = AsyncMock(return_value=Cursor(dense))
    monkeypatch.setattr(storage.SharedSpaceStorageReader, "open_milvus_cursor", dense_open)
    if case != "es_init_failure":
        monkeypatch.setattr(storage.SharedSpaceStorageReader, "open_es_cursor", AsyncMock(return_value=Cursor(sparse)))

    async def rerank(**kwargs):
        assert checks == [(0, [1])]
        assert len(kwargs["candidates"]) == 2
        return kwargs["candidates"]

    monkeypatch.setattr(WorkStationService, "_rerank_retrieval_candidates", rerank)

    plan = QaRetrievalPlan((10,))
    if case == "favorite_removed":
        from test.knowledge.test_portal_qa_favorites import fixture
        from bisheng.knowledge.domain.services import portal_qa_favorites
        favorite_resolver, _, _ = fixture()
        binding = await favorite_resolver.resolve(90, 100)
        plan = QaRetrievalPlan((10,), {10: [1]}, favorite_bindings=(binding,))

        def current_favorites(*args):
            if len(sessions) > 1:
                favorite_resolver.files.rows.pop(100, None)
            return favorite_resolver

        monkeypatch.setattr(portal_qa_favorites, "create_qa_favorites", current_favorites)

    async def run():
        return await retrieve_portal_qa(
            request=None,
            user=SimpleNamespace(user_id=42, tenant_id=7),
            plan=plan,
            query="question",
            config=KnowledgeRetrievalRuntimeConf(),
            max_chars=1000,
        )

    if case in {"revoke", "favorite_removed"}:
        with pytest.raises(QaRetrievalError, match="scope changed"):
            await run()
    else:
        documents, result = await run()
        assert len(documents) == 2
        assert result.scope_complete == (case == "normal")
        assert bool(result.degraded_reasons) == (case != "normal")
        assert all(doc.metadata["entry_file_id"] == 1 for doc in documents)
    assert checks == ([(0, [1])] if case == "favorite_removed" else [(0, [1]), (1, [1])])
    assert sessions == [0, 1]
    assert closed == [1, 0]
    assert dense.await_count == (0 if case == "embedding_failure" else 1)
    assert sparse.await_count == (0 if case == "es_init_failure" else 1)
    if case == "es_init_failure":
        es_client.assert_awaited_once()
        assert "keyword_unavailable" in result.degraded_reasons
    if case != "embedding_failure":
        assert dense_open.await_args.kwargs["filter_"].requested_space_ids == (10,)


@pytest.mark.parametrize("filters", [{}, {10: []}])
async def test_explicit_empty_never_calls_storage(filters):
    documents, result = await retrieve_portal_qa(
        request=None, user=None, plan=QaRetrievalPlan((10,), filters), query="q", config=None, max_chars=10
    )
    assert documents == [] and result.scope_complete

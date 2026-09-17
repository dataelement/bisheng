"""实际统一编排与 Resolver 的集成边界，外部存储和身份服务用可控替身。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf
from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan, QaRetrievalError, unified_qa_enabled
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


@pytest.mark.parametrize("revoke", [False, True])
async def test_pipeline_authorizes_before_rerank_and_freshly_before_model(monkeypatch, revoke):
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
        allowed = not (revoke and phase == 1)
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
    monkeypatch.setattr(manager, "get_es_connection", AsyncMock(return_value=object()))
    monkeypatch.setattr(LLMService, "aget_knowledge_default_embedding", AsyncMock(return_value=object()))
    dense, sparse = AsyncMock(return_value=[hit(), hit(chunk_index=1)]), AsyncMock(return_value=[])

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
    monkeypatch.setattr(storage.SharedSpaceStorageReader, "open_es_cursor", AsyncMock(return_value=Cursor(sparse)))

    async def rerank(**kwargs):
        assert checks == [(0, [1])]
        assert len(kwargs["candidates"]) == 2
        return kwargs["candidates"]

    monkeypatch.setattr(WorkStationService, "_rerank_retrieval_candidates", rerank)

    async def run():
        return await retrieve_portal_qa(
            request=None,
            user=SimpleNamespace(user_id=42, tenant_id=7),
            plan=QaRetrievalPlan((10,)),
            query="question",
            config=KnowledgeRetrievalRuntimeConf(),
            max_chars=1000,
        )

    if revoke:
        with pytest.raises(QaRetrievalError, match="scope changed"):
            await run()
    else:
        documents, result = await run()
        assert len(documents) == 2 and result.scope_complete
        assert all(doc.metadata["entry_file_id"] == 1 for doc in documents)
    assert checks == [(0, [1]), (1, [1])]
    assert sessions == [0, 1]
    assert closed == [1, 0]
    assert dense.await_count == sparse.await_count == 1
    assert dense_open.await_args.kwargs["filter_"].requested_space_ids == (10,)


@pytest.mark.parametrize("filters", [{}, {10: []}])
async def test_explicit_empty_never_calls_storage(filters):
    documents, result = await retrieve_portal_qa(
        request=None, user=None, plan=QaRetrievalPlan((10,), filters), query="q", config=None, max_chars=10
    )
    assert documents == [] and result.scope_complete


def test_gate_requires_enabled_tenant_and_optional_user():
    config = KnowledgeRetrievalRuntimeConf()
    user = SimpleNamespace(user_id=42, tenant_id=7)
    assert not unified_qa_enabled(config, user)
    config.portal_unified_qa_enabled = True
    assert not unified_qa_enabled(config, user)
    config.portal_unified_qa_tenant_ids = [7]
    assert unified_qa_enabled(config, user)
    config.portal_unified_qa_user_ids = [43]
    assert not unified_qa_enabled(config, user)
    config.portal_unified_qa_user_ids = [42]
    assert unified_qa_enabled(config, user)

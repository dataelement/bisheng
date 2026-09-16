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
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.repositories.implementations import (
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
    monkeypatch.setattr(
        docs, "KnowledgeDocumentRepositoryImpl", lambda session: StubDocumentRepository([make_document()])
    )
    monkeypatch.setattr(versions, "KnowledgeDocumentVersionRepositoryImpl", lambda session: StubVersionRepository([]))
    monkeypatch.setattr(grants, "DepartmentFileViewGrantRepositoryImpl", lambda session: object())

    def access_service(**kwargs):
        async def evaluate_files(*, login_user, files):
            checks.append((kwargs["session"], [f.id for f in files]))
            allowed = not (revoke and kwargs["session"] == 1)
            return {f.id: SimpleNamespace(status="allowed" if allowed else "approval_required") for f in files}

        return SimpleNamespace(evaluate_files=evaluate_files)

    monkeypatch.setattr(access, "DepartmentFileViewAccessService", access_service)
    monkeypatch.setattr(
        KnowledgeSpaceChatService,
        "_permission_service",
        lambda self: SimpleNamespace(_require_read_permission=AsyncMock()),
    )
    monkeypatch.setattr(
        KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=[SimpleNamespace(id=10, tenant_id=7, type=2)])
    )
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
    monkeypatch.setattr(storage.SharedSpaceStorageReader, "search_milvus", dense)
    monkeypatch.setattr(storage.SharedSpaceStorageReader, "search_es", sparse)

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
    assert sessions == closed == [0, 1]
    assert dense.await_count == sparse.await_count == 1
    assert dense.await_args.kwargs["filter_"].requested_space_ids == (10,)


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

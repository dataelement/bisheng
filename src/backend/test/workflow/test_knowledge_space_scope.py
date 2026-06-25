import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.workflow.common.knowledge import (
    RagUtils,
    ensure_knowledge_space_login_user,
    retrieve_knowledge_space_documents_sync,
)
from bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever import KnowledgeRetriever
from bisheng.workflow.nodes.qa_retriever.qa_retriever import (
    QARetrieverNode,
    normalize_qa_knowledge_value,
)


@pytest.mark.asyncio
async def test_authorized_space_options_filter_and_paginate():
    svc = object.__new__(KnowledgeSpaceService)

    async def _get_grouped_spaces(order_by="name"):
        return SimpleNamespace(
            public_spaces=[SimpleNamespace(id=1, name="Alpha Space")],
            department_spaces=[SimpleNamespace(id=2, name="Beta Space")],
            team_spaces=[],
            personal_spaces=[SimpleNamespace(id=3, name="Gamma")],
        )

    svc.get_grouped_spaces = _get_grouped_spaces

    result = await svc.get_authorized_space_options(keyword="space", page=2, page_size=1)

    assert result["total"] == 2
    assert result["has_more"] is False
    assert [item.id for item in result["data"]] == [2]


def test_init_multi_retriever_uses_explicit_space_branch():
    obj = object.__new__(RagUtils)
    obj._knowledge_type = "space"
    calls = []

    obj.init_knowledge_retriever = lambda: calls.append("knowledge")
    obj.init_file_retriever = lambda: calls.append("tmp")
    obj.init_space_retriever = lambda: calls.append("space")

    obj.init_multi_retriever()

    assert calls == ["space"]


def test_init_multi_retriever_rejects_unknown_type():
    obj = object.__new__(RagUtils)
    obj._knowledge_type = "unexpected"
    obj.init_knowledge_retriever = MagicMock()
    obj.init_file_retriever = MagicMock()
    obj.init_space_retriever = MagicMock()

    with pytest.raises(ValueError, match="Unsupported knowledge retrieval type"):
        obj.init_multi_retriever()


def test_init_space_retriever_rejects_empty_selection():
    obj = object.__new__(RagUtils)
    obj._knowledge_value = []

    with pytest.raises(ValueError, match="requires at least one selected space"):
        obj.init_space_retriever()


def test_knowledge_retriever_space_errors_are_node_errors():
    obj = object.__new__(KnowledgeRetriever)
    obj._knowledge_type = "space"
    obj._output_keys = ["retrieved_result"]
    obj.init_user_question = lambda: ["question"]
    obj.init_user_info = lambda: None
    obj.init_multi_retriever = lambda: None
    obj.init_rerank_model = lambda: None
    obj.retrieve_question = MagicMock(side_effect=RuntimeError("space denied"))

    with pytest.raises(RuntimeError, match="space denied"):
        obj._run("unique")


def test_retrieve_space_question_uses_space_service(monkeypatch):
    obj = object.__new__(RagUtils)
    obj._knowledge_value = [12]
    obj._retriever_kwargs = {"k": 100}
    obj._max_chunk_size = 4096
    obj.user_info = SimpleNamespace(user_id=7, user_name="tester")

    captured = {}

    def _fake_retrieve(**kwargs):
        captured.update(kwargs)
        return [(12, Document(page_content="chunk", metadata={}))]

    monkeypatch.setattr(
        "bisheng.workflow.common.knowledge.retrieve_knowledge_space_documents_sync",
        _fake_retrieve,
    )

    docs = obj.retrieve_space_question("question")

    assert captured["knowledge_base_ids"] == [12]
    assert captured["query"] == "question"
    assert captured["top_k"] == 100
    assert captured["max_content"] == 4096
    assert docs[0].page_content == "chunk"
    assert docs[0].metadata["knowledge_space_id"] == 12


def test_knowledge_space_login_user_adapter_accepts_orm_user():
    orm_user = SimpleNamespace(
        user_id=7,
        user_name="tester",
        user_role=[2],
        tenant_id=1,
    )

    login_user = ensure_knowledge_space_login_user(orm_user)

    assert login_user.user_id == 7
    assert login_user.user_name == "tester"
    assert hasattr(login_user, "get_user_group_ids")


def test_knowledge_space_login_user_adapter_preserves_compatible_user():
    login_user = SimpleNamespace(
        user_id=7,
        user_name="tester",
        get_user_group_ids=lambda _user_id: [],
    )

    assert ensure_knowledge_space_login_user(login_user) is login_user


def test_knowledge_space_retrieve_helper_injects_version_repo(monkeypatch):
    created = {}

    worker_mod = types.ModuleType("bisheng.worker")
    worker_mod.__path__ = []
    asyncio_utils_mod = types.ModuleType("bisheng.worker._asyncio_utils")
    asyncio_utils_mod.run_async_task = lambda coro_factory: asyncio.run(coro_factory())
    worker_mod._asyncio_utils = asyncio_utils_mod
    monkeypatch.setitem(sys.modules, "bisheng.worker", worker_mod)
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", asyncio_utils_mod)

    class FakeSessionContext:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeVersionRepo:
        def __init__(self, session):
            self.session = session
            created["repo"] = self

    class FakeChatService:
        def __init__(self, request, login_user):
            self.request = request
            self.login_user = login_user
            created["service"] = self

        async def aretrieve_chunks(self, **kwargs):
            assert self.version_repo is created["repo"]
            assert self.version_repo.session == "session"
            created["kwargs"] = kwargs
            return [(12, Document(page_content="chunk", metadata={}))]

    monkeypatch.setattr(
        "bisheng.core.database.get_async_db_session",
        lambda: FakeSessionContext(),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations."
        "knowledge_document_version_repository_impl.KnowledgeDocumentVersionRepositoryImpl",
        FakeVersionRepo,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeSpaceChatService",
        FakeChatService,
    )

    result = retrieve_knowledge_space_documents_sync(
        request=object(),
        login_user=SimpleNamespace(user_id=7, user_name="tester"),
        query="question",
        knowledge_base_ids=[12],
        top_k=5,
        max_content=1024,
    )

    assert result[0][1].page_content == "chunk"
    assert created["kwargs"]["knowledge_base_ids"] == [12]
    assert created["kwargs"]["top_k"] == 5
    assert created["kwargs"]["max_content"] == 1024


def test_normalize_qa_knowledge_value_preserves_old_array_shape():
    knowledge_type, ids = normalize_qa_knowledge_value(
        [
            {"key": 10, "label": "QA"},
        ]
    )

    assert knowledge_type == "qa"
    assert ids == [10]


def test_normalize_qa_knowledge_value_supports_space_shape():
    knowledge_type, ids = normalize_qa_knowledge_value(
        {
            "type": "space",
            "value": [{"key": 20, "label": "Space"}],
        }
    )

    assert knowledge_type == "space"
    assert ids == [20]


def test_qa_space_branch_returns_document_content_without_qa_metadata(monkeypatch):
    obj = object.__new__(QARetrieverNode)
    obj.id = "qa-node"
    obj.user_info = SimpleNamespace(user_id=7, user_name="tester")
    obj._qa_knowledge_id = [20]
    graph_state = MagicMock()
    obj.graph_state = graph_state

    def _fake_retrieve(**kwargs):
        return [(20, Document(page_content="space answer", metadata={}))]

    monkeypatch.setattr(
        "bisheng.workflow.nodes.qa_retriever.qa_retriever.retrieve_knowledge_space_documents_sync",
        _fake_retrieve,
    )

    result = obj._retrieve_space_answer("question")

    assert result == "space answer"
    graph_state.set_variable.assert_called_once()

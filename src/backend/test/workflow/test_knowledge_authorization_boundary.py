"""Client auth toggles cannot turn ordinary KB retrieval into an unchecked collection read."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.parametrize("toggle,expected_user", [(True, 7), (False, 22)])
def test_rag_filters_references_before_constructing_vector_clients(monkeypatch, toggle, expected_user):
    from bisheng.knowledge.domain.services import workflow_knowledge_authorization as auth
    from bisheng.workflow.common.knowledge import RagUtils

    node = object.__new__(RagUtils)
    node.user_id = 7
    node.flow_user_id = 22
    node.tenant_id = 1
    node._knowledge_auth = toggle
    node._knowledge_value = [11, 99]
    node._knowledge_vector_list = {}
    node._keyword_weight = 0.5
    node._vector_weight = 0.5
    node._retriever_kwargs = {"k": 100}
    node.user_info = SimpleNamespace(user_name="runtime")
    node._fetch_non_primary_file_ids = Mock(return_value=[])
    allowed = Mock(return_value=[11])
    monkeypatch.setattr(auth, "authorized_knowledge_ids", allowed)
    vector = Mock(return_value={})
    monkeypatch.setattr("bisheng.workflow.common.knowledge.KnowledgeRag.get_multi_knowledge_vectorstore_sync", vector)
    node.init_knowledge_retriever()
    allowed.assert_called_once_with(identity_user_id=expected_user, tenant_id=1, knowledge_ids=[11, 99])
    assert vector.call_args.kwargs["knowledge_ids"] == [11]
    node._knowledge_vector_list = {99: {"knowledge": object()}}
    allowed.return_value = []
    vector.reset_mock()
    node.init_knowledge_retriever()
    assert node._knowledge_vector_list == {}
    assert node._multi_milvus_retriever is None and node._multi_es_retriever is None
    vector.assert_not_called()


def test_qa_does_not_use_hardcoded_auth_bypass_without_checked_ids(monkeypatch):
    from bisheng.knowledge.domain.services import workflow_knowledge_authorization as auth
    from bisheng.workflow.nodes.qa_retriever.qa_retriever import QARetrieverNode

    node = object.__new__(QARetrieverNode)
    node.user_id = 7
    node.tenant_id = 1
    node._qa_knowledge_id = [99]
    node._retriever = None
    node._score = 0.6
    node.user_info = SimpleNamespace(user_name="runtime")
    allowed = Mock(return_value=[])
    monkeypatch.setattr(auth, "authorized_knowledge_ids", allowed)
    vectors = Mock(return_value={})
    monkeypatch.setattr(
        "bisheng.workflow.nodes.qa_retriever.qa_retriever.KnowledgeRag.get_multi_knowledge_vectorstore_sync", vectors
    )
    node._init_retriever()
    allowed.assert_called_once_with(identity_user_id=7, tenant_id=1, knowledge_ids=[99])
    assert not vectors.called or vectors.call_args.kwargs["knowledge_ids"] == []


@pytest.mark.parametrize("identity", [None, SimpleNamespace(user_id=7)])
async def test_authority_helper_never_returns_unpermitted_ids(monkeypatch, identity):
    from bisheng.knowledge.domain.services import workflow_knowledge_authorization as auth

    monkeypatch.setattr(auth, "abuild_scoped_login_user", AsyncMock(return_value=identity))
    monkeypatch.setattr(auth.KnowledgeRag, "afilter_usable_knowledge_ids", AsyncMock(return_value={11}))
    monkeypatch.setattr(
        auth.KnowledgeDao,
        "aget_list_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id=11, tenant_id=1), SimpleNamespace(id=99, tenant_id=1)]),
    )
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(1)
    try:
        result = await auth.aauthorized_knowledge_ids(identity_user_id=7, tenant_id=1, knowledge_ids=[11, 99])
        assert result == ([] if identity is None else [11])
    finally:
        current_tenant_id.reset(token)


async def test_foreign_rows_cannot_pass_even_when_policy_stub_allows(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id
    from bisheng.knowledge.domain.services import workflow_knowledge_authorization as auth

    monkeypatch.setattr(auth, "abuild_scoped_login_user", AsyncMock(return_value=SimpleNamespace(user_id=7)))
    monkeypatch.setattr(auth.KnowledgeRag, "afilter_usable_knowledge_ids", AsyncMock(return_value={99}))
    monkeypatch.setattr(
        auth.KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=[SimpleNamespace(id=99, tenant_id=8)])
    )
    token = current_tenant_id.set(1)
    try:
        assert await auth.aauthorized_knowledge_ids(identity_user_id=7, tenant_id=1, knowledge_ids=[99]) == []
    finally:
        current_tenant_id.reset(token)

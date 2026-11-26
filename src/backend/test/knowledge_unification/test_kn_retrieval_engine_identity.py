"""The actual retrieval loop preserves original identity and file filtering.

覆盖 AC: AC-37, AC-68, AC-79, AC-89, AC-92.
Only vector and F029 permission transports are isolated; the real retrieval
engine loop must forward the original compatible user, principal and actor.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from langchain_core.documents import Document

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services import retrieval_engine as module
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine
from bisheng.open_api.domain.context import (
    OpenApiPrincipal,
    get_current_open_api_principal,
    reset_current_open_api_principal,
    set_current_open_api_principal,
)
from bisheng.permission.application.identity import (
    PermissionActor,
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)


async def test_real_retrieval_loop_forwards_original_user_and_keeps_both_file_filters(monkeypatch):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[5])
    actor = PermissionActor(subject_type="service_account", subject_id=91, tenant_id=101)
    principal = OpenApiPrincipal(
        credential_id=42,
        actor_kind="service_account",
        actor_id=91,
        actor_name="service",
        tenant_id=101,
        resource_owner_user_id=7,
        scopes=frozenset({"filelib:retrieve"}),
        authorization_subject_type="service_account",
        authorization_subject_id=91,
        effective_user_id=None,
    )
    space = Knowledge(id=40, name="Space", tenant_id=101, type=3, model="11")
    engine = RetrievalEngine(user)
    visibility = SimpleNamespace(
        build_index_prefilter=AsyncMock(
            return_value=SimpleNamespace(
                is_empty=False, accessible_size=2, strategy="ids", milvus_expr="document_id in [1,2]", es_filter=[]
            )
        ),
        post_filter_retrievable_files=AsyncMock(return_value={1}),
    )
    engine._knowledge_file_visibility_service = visibility
    monkeypatch.setattr(
        engine,
        "_qa_filter_conf",
        lambda: SimpleNamespace(retrieval_initial_multiplier=1, retrieval_expansion_multiplier=2),
    )

    async def vector(*args, **kwargs):
        assert kwargs.get("login_user") is user
        assert kwargs["knowledge"] is space
        assert get_current_permission_actor() is actor
        assert get_current_open_api_principal() is principal
        return Mock()

    milvus, es = AsyncMock(side_effect=vector), AsyncMock(side_effect=vector)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", milvus)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", es)
    allowed = Document(page_content="allowed", metadata={"document_id": 1})
    denied = Document(page_content="denied", metadata={"document_id": 2})
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value=[allowed, denied]))
    monkeypatch.setattr(module, "KnowledgeRetrieverTool", Mock(return_value=tool))
    actor_token, principal_token = set_current_permission_actor(actor), set_current_open_api_principal(principal)
    try:
        with tenant_execution_scope(101):
            result = await engine.retrieve_and_filter(
                space=space, query="q", candidate_file_ids=[1, 2], max_content=100
            )
        assert result == [allowed]
        visibility.build_index_prefilter.assert_awaited_once_with(40, [1, 2])
        visibility.post_filter_retrievable_files.assert_awaited_once_with(40, {1, 2})
        milvus.assert_awaited_once()
        es.assert_awaited_once()
        assert user.user_id == 7 and user.user_role == [5]
    finally:
        reset_current_open_api_principal(principal_token)
        reset_current_permission_actor(actor_token)

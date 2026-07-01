"""F041 unit tests — space retrieval helpers (identity, no tenant switch).

Covers design decision 2/3 + gotcha 5.10: building the config-author identity for
knowledge-space retrieval must NOT switch the current tenant ContextVar.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.documents import Document

from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services import space_flow_retrieval
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter


async def test_scoped_login_user_no_tenant_switch():
    """abuild_scoped_login_user builds the author payload without touching the
    current tenant ContextVar (gotcha 5.10)."""
    set_current_tenant_id(7)  # flow tenant already in context

    fake_user = SimpleNamespace(user_id=42, user_name="author")
    fake_payload = SimpleNamespace(user_id=42, user_name="author", tenant_id=7)

    with (
        patch.object(space_flow_retrieval.UserDao, "aget_user", AsyncMock(return_value=fake_user)),
        patch.object(
            space_flow_retrieval.UserPayload,
            "init_login_user",
            AsyncMock(return_value=fake_payload),
        ) as init_mock,
    ):
        result = await space_flow_retrieval.abuild_scoped_login_user(user_id=42, tenant_id=7)

    assert result is fake_payload
    # Identity built within the passed (flow) tenant, not the author's active tenant.
    assert init_mock.await_args.kwargs["tenant_id"] == 7
    assert init_mock.await_args.kwargs["user_id"] == 42
    # The crucial invariant: current tenant is untouched.
    assert get_current_tenant_id() == 7


async def test_scoped_login_user_none_when_missing():
    """No user_id / unknown user → None (caller treats as 'no visible files')."""
    assert await space_flow_retrieval.abuild_scoped_login_user(user_id=None, tenant_id=1) is None

    with patch.object(space_flow_retrieval.UserDao, "aget_user", AsyncMock(return_value=None)):
        assert await space_flow_retrieval.abuild_scoped_login_user(user_id=999, tenant_id=1) is None


# --- filter-combination helpers (pure) ---


def test_and_milvus_expr_combines_and_skips_empty():
    assert space_flow_retrieval._and_milvus_expr(None, None) is None
    assert space_flow_retrieval._and_milvus_expr("document_id in [1]", None) == "(document_id in [1])"
    assert (
        space_flow_retrieval._and_milvus_expr("document_id in [1]", "meta == 'x'")
        == "(document_id in [1]) and (meta == 'x')"
    )


def test_merge_es_clauses_concats():
    assert space_flow_retrieval._merge_es_clauses(None, None) == []
    assert space_flow_retrieval._merge_es_clauses([{"a": 1}], None, [{"b": 2}]) == [{"a": 1}, {"b": 2}]


# --- aretrieve_space_documents guards + drop logic ---


async def test_aretrieve_returns_empty_when_no_identity_or_spaces():
    assert (
        await space_flow_retrieval.aretrieve_space_documents(
            space_ids=[5], query="q", identity_user=None, max_content=1000
        )
        == []
    )
    ident = SimpleNamespace(user_id=1, is_admin=lambda: False)
    assert (
        await space_flow_retrieval.aretrieve_space_documents(
            space_ids=[], query="q", identity_user=ident, max_content=1000
        )
        == []
    )


def _mock_retrieval(
    vis_instance, docs, retriever_cls_target="bisheng.tool.domain.langchain.knowledge.KnowledgeRetrieverTool"
):
    """Patch the heavy retrieval deps of _aretrieve_one_space (Milvus/ES = 测试降级)."""
    vector = MagicMock()
    vector.as_retriever = MagicMock(return_value=MagicMock())
    rag = MagicMock()
    rag.init_knowledge_milvus_vectorstore = AsyncMock(return_value=vector)
    rag.init_knowledge_es_vectorstore = AsyncMock(return_value=vector)
    tool_instance = MagicMock()
    tool_instance.ainvoke = AsyncMock(return_value=docs)
    return (
        patch("bisheng.knowledge.domain.knowledge_rag.KnowledgeRag", rag),
        patch(retriever_cls_target, MagicMock(return_value=tool_instance)),
    )


async def test_space_filter_open_runtime_drops_unauthorized():
    """AC-12/AC-13: only files the (runtime) user has view_file on survive."""
    runtime = SimpleNamespace(user_id=7, is_admin=lambda: False)
    space = SimpleNamespace(id=5)

    doc_ok = Document(page_content="ok", metadata={"document_id": 1})
    doc_no = Document(page_content="nope", metadata={"document_id": 2})

    vis = MagicMock()
    vis.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", milvus_expr="document_id in [1, 2]", es_filter=[], accessible_size=2)
    )
    vis.post_filter_visible_files = AsyncMock(return_value={1})  # only file 1 visible
    vis._config = MagicMock(
        return_value=SimpleNamespace(retrieval_initial_multiplier=1, retrieval_expansion_multiplier=2)
    )
    vis_cls = MagicMock(return_value=vis)

    rag_patch, tool_patch = _mock_retrieval(vis, [doc_ok, doc_no])
    with (
        patch("bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id", AsyncMock(return_value=space)),
        patch(
            "bisheng.knowledge.domain.services.knowledge_file_visibility_service.KnowledgeFileVisibilityService",
            vis_cls,
        ),
        rag_patch,
        tool_patch,
    ):
        result = await space_flow_retrieval.aretrieve_space_documents(
            space_ids=[5], query="q", identity_user=runtime, max_content=1000
        )

    assert [d.metadata["document_id"] for d in result] == [1]  # unauthorized doc 2 dropped
    # Visibility service built with the runtime identity (AC-12).
    assert vis_cls.call_args.args[1] is runtime


async def test_space_filter_close_author_identity():
    """AC-14: toggle OFF filters by the config-author identity (not the runtime user)."""
    author = SimpleNamespace(user_id=99, is_admin=lambda: False)
    space = SimpleNamespace(id=5)
    doc = Document(page_content="c", metadata={"document_id": 1})

    vis = MagicMock()
    vis.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", milvus_expr="document_id in [1]", es_filter=[], accessible_size=1)
    )
    vis.post_filter_visible_files = AsyncMock(return_value={1})
    vis._config = MagicMock(
        return_value=SimpleNamespace(retrieval_initial_multiplier=1, retrieval_expansion_multiplier=2)
    )
    vis_cls = MagicMock(return_value=vis)

    rag_patch, tool_patch = _mock_retrieval(vis, [doc])
    with (
        patch("bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id", AsyncMock(return_value=space)),
        patch(
            "bisheng.knowledge.domain.services.knowledge_file_visibility_service.KnowledgeFileVisibilityService",
            vis_cls,
        ),
        rag_patch,
        tool_patch,
    ):
        result = await space_flow_retrieval.aretrieve_space_documents(
            space_ids=[5], query="q", identity_user=author, max_content=1000
        )

    assert len(result) == 1
    assert vis_cls.call_args.args[1] is author  # author drives the filter

"""F046 publication/deletion hard-deny coverage for F030 OpenAPI paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.api.endpoints import filelib


def _login_user(*, user_id: int = 7, tenant_id: int = 42):
    user = MagicMock()
    user.user_id = user_id
    user.user_name = f"user-{user_id}"
    user.tenant_id = tenant_id
    user.is_admin = MagicMock(return_value=False)
    user.is_global_super = False
    return user


def _doc(file_id: int) -> Document:
    return Document(
        page_content=f"chunk-{file_id}",
        metadata={"document_id": file_id, "document_name": f"file-{file_id}.pdf"},
    )


def _bound_resolver(user):
    async def resolve(_user_id):
        set_current_tenant_id(int(user.tenant_id))
        return user

    return AsyncMock(side_effect=resolve)


@pytest.fixture(autouse=True)
def _reset_tenant_context():
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


async def test_v2_space_file_list_uses_owner_service_for_publication_guard(monkeypatch):
    """The OpenAPI endpoint must not implement a second ORM listing path."""
    user = _login_user(user_id=91)
    resolve = _bound_resolver(user)
    monkeypatch.setattr(filelib, "resolve_operator", resolve)
    monkeypatch.setattr(
        filelib.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=42)),
    )
    guarded_page = MagicMock()
    guarded_page.model_dump.return_value = {
        "data": [{"id": 103, "file_name": "published.pdf"}],
        "page_size": 20,
        "has_more": False,
        "next_cursor": None,
    }
    list_children = AsyncMock(return_value=guarded_page)
    monkeypatch.setattr(KnowledgeSpaceService, "list_space_children", list_children)
    monkeypatch.setattr(
        KnowledgeSpaceService,
        "can_write_space_container",
        AsyncMock(return_value=False),
    )

    response = await filelib.get_filelist(
        request=MagicMock(),
        knowledge_id=8,
        parent_id=3,
        keyword=None,
        status=None,
        page_size=20,
        cursor=None,
        user_id=91,
        version_repo=MagicMock(),
        doc_repo=MagicMock(),
    )

    assert response.data["data"] == [{"id": 103, "file_name": "published.pdf"}]
    resolve.assert_awaited_once_with(91)
    list_children.assert_awaited_once_with(
        8,
        parent_id=3,
        file_status=None,
        cursor=None,
        page_size=20,
    )


async def test_v2_space_keyword_search_uses_guarded_owner_search(monkeypatch):
    user = _login_user(user_id=92)
    monkeypatch.setattr(filelib, "resolve_operator", _bound_resolver(user))
    monkeypatch.setattr(
        filelib.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=42)),
    )
    guarded_page = MagicMock()
    guarded_page.model_dump.return_value = {
        "data": [],
        "page_size": 10,
        "has_more": False,
        "next_cursor": None,
    }
    search = AsyncMock(return_value=guarded_page)
    list_children = AsyncMock(side_effect=AssertionError("keyword search must not use raw children path"))
    monkeypatch.setattr(KnowledgeSpaceService, "asearch_space_children_cursor", search)
    monkeypatch.setattr(KnowledgeSpaceService, "list_space_children", list_children)
    monkeypatch.setattr(
        KnowledgeSpaceService,
        "can_write_space_container",
        AsyncMock(return_value=True),
    )

    response = await filelib.get_filelist(
        request=MagicMock(),
        knowledge_id=8,
        parent_id=None,
        keyword="secret",
        status=None,
        page_size=10,
        cursor=None,
        user_id=92,
        version_repo=MagicMock(),
        doc_repo=MagicMock(),
    )

    assert response.data["data"] == []
    search.assert_awaited_once_with(
        8,
        parent_id=None,
        keyword="secret",
        file_status=None,
        page_size=10,
        cursor=None,
    )
    list_children.assert_not_awaited()


async def test_v2_space_file_list_denies_cross_tenant_row_before_owner_service(monkeypatch):
    user = _login_user(user_id=93, tenant_id=42)
    monkeypatch.setattr(filelib, "resolve_operator", _bound_resolver(user))
    monkeypatch.setattr(
        filelib.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value, tenant_id=43)),
    )
    list_children = AsyncMock()
    monkeypatch.setattr(KnowledgeSpaceService, "list_space_children", list_children)

    with pytest.raises(Exception) as exc_info:
        await filelib.get_filelist(
            request=MagicMock(),
            knowledge_id=8,
            parent_id=None,
            keyword=None,
            status=None,
            page_size=20,
            cursor=None,
            user_id=93,
            version_repo=MagicMock(),
            doc_repo=MagicMock(),
        )

    assert getattr(exc_info.value, "status_code", None) == 404
    list_children.assert_not_awaited()


async def test_v2_space_file_list_denies_row_without_explicit_tenant_before_owner_service(monkeypatch):
    user = _login_user(user_id=94, tenant_id=42)
    monkeypatch.setattr(filelib, "resolve_operator", _bound_resolver(user))
    monkeypatch.setattr(
        filelib.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=KnowledgeTypeEnum.SPACE.value)),
    )
    list_children = AsyncMock()
    monkeypatch.setattr(KnowledgeSpaceService, "list_space_children", list_children)

    with pytest.raises(Exception) as exc_info:
        await filelib.get_filelist(
            request=MagicMock(),
            knowledge_id=8,
            parent_id=None,
            keyword=None,
            status=None,
            page_size=20,
            cursor=None,
            user_id=94,
            version_repo=MagicMock(),
            doc_repo=MagicMock(),
        )

    assert getattr(exc_info.value, "status_code", None) == 404
    list_children.assert_not_awaited()


async def test_v2_space_retrieve_reuses_visibility_prefilter_and_postfilter(monkeypatch):
    """Index residue must not let unpublished/deleted chunks reach OpenAPI output."""
    set_current_tenant_id(42)
    service = KnowledgeSpaceChatService(request=MagicMock(), login_user=_login_user())
    service.version_repo = MagicMock()
    service._require_space_view_permission = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=8)),
    )
    service._resolve_kb_target_file_ids = AsyncMock(return_value=None)

    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(
            strategy="notin",
            milvus_expr="document_id not in [101, 102]",
            es_filter=[{"bool": {"must_not": {"terms": {"metadata.document_id": [101, 102]}}}}],
        )
    )
    visibility.post_filter_visible_files = AsyncMock(return_value={103})
    visibility.project_mutation_retrieval_query = AsyncMock(return_value="q")
    visibility.project_mutation_retrieval_names = AsyncMock(side_effect=lambda **kwargs: kwargs["documents"])
    service._knowledge_file_visibility_service = visibility

    milvus_store = MagicMock()
    es_store = MagicMock()
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
            AsyncMock(return_value=milvus_store),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
            AsyncMock(return_value=es_store),
        ),
        patch("bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool") as tool_factory,
    ):
        tool_factory.return_value.ainvoke = AsyncMock(return_value=[_doc(101), _doc(102), _doc(103)])
        results = await service._aretrieve_chunks_for_kb(
            8,
            query="q",
            tag_names=[],
            max_content=1000,
        )

    assert [(space_id, int(doc.metadata["document_id"])) for space_id, doc in results] == [(8, 103)]
    visibility.build_index_prefilter.assert_awaited_once_with(8, None)
    visibility.post_filter_visible_files.assert_awaited_once_with(8, {101, 102, 103})
    milvus_store.as_retriever.assert_called_once()
    assert milvus_store.as_retriever.call_args.kwargs["search_kwargs"]["expr"] == ("document_id not in [101, 102]")


@pytest.mark.parametrize(
    ("tenant_id", "context_tenant_id", "error_type"),
    [
        (0, 42, ValueError),
        (42, None, ValueError),
        (42, 1, RuntimeError),
    ],
)
async def test_v2_space_retrieve_fails_closed_without_matching_explicit_identity(
    monkeypatch,
    tenant_id,
    context_tenant_id,
    error_type,
):
    if context_tenant_id is not None:
        set_current_tenant_id(context_tenant_id)
    service = KnowledgeSpaceChatService(
        request=MagicMock(),
        login_user=_login_user(user_id=7, tenant_id=tenant_id),
    )
    service.version_repo = MagicMock()
    service._require_space_view_permission = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=8)),
    )
    service._resolve_kb_target_file_ids = AsyncMock(return_value=None)

    with pytest.raises(error_type):
        await service._aretrieve_chunks_for_kb(
            8,
            query="q",
            tag_names=[],
            max_content=1000,
        )


async def test_v2_retrieve_endpoint_binds_visibility_to_impersonated_user(monkeypatch):
    acting_user = _login_user(user_id=97)
    set_current_tenant_id(42)
    resolve = AsyncMock(return_value=acting_user)
    monkeypatch.setattr(filelib, "resolve_operator", resolve)
    captured = {}

    async def retrieve(self, **kwargs):
        captured["login_user"] = self.login_user
        captured["version_repo"] = self.version_repo
        return []

    monkeypatch.setattr(KnowledgeSpaceChatService, "aretrieve_chunks", retrieve)
    req = SimpleNamespace(
        user_id=97,
        filters=None,
        query="q",
        knowledge_base_ids=[8],
        top_k=10,
        max_content=1000,
    )
    version_repo = MagicMock()

    response = await filelib.retrieve_chunks(
        request=MagicMock(),
        req=req,
        version_repo=version_repo,
    )

    assert response.data.total == 0
    assert captured == {"login_user": acting_user, "version_repo": version_repo}
    resolve.assert_awaited_once_with(97)

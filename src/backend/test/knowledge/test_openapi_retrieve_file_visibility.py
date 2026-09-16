"""F053 file-level isolation for both Open API retrieve branches."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def service() -> KnowledgeSpaceChatService:
    login_user = MagicMock(user_id=99)
    result = KnowledgeSpaceChatService(request=MagicMock(), login_user=login_user)
    result.version_repo = MagicMock()
    return result


def doc(file_id: int, content: str) -> Document:
    return Document(page_content=content, metadata={"document_id": file_id})


@pytest.mark.parametrize(
    ("knowledge_type", "method_name"),
    [
        (KnowledgeTypeEnum.SPACE.value, "retrieve_space"),
        (KnowledgeTypeEnum.NORMAL.value, "retrieve_library"),
    ],
)
async def test_both_retrieve_branches_use_the_shared_file_filter(
    monkeypatch,
    knowledge_type,
    method_name,
):
    """F052 T101: both branches still land on the one filtered retrieval loop."""

    engine = RetrievalEngine(MagicMock(user_id=99), version_repo=MagicMock())
    kb = MagicMock(id=8, type=knowledge_type, user_id=4)
    engine.resolve_space_file_ids_by_tags = AsyncMock(return_value=[10, 11])
    engine.resolve_library_file_ids_by_tags = AsyncMock(return_value=[10, 11])
    engine.retrieve_and_filter = AsyncMock(return_value=[doc(10, "allowed")])
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service."
        "KnowledgeService.permission_service.ensure_knowledge_use_async",
        AsyncMock(),
    )

    method = getattr(engine, method_name)
    result = await method(kb, query="q", tag_names=["tag"], max_content=100)

    assert [(kb_id, item.page_content) for kb_id, item in result] == [(8, "allowed")]
    engine.retrieve_and_filter.assert_awaited_once_with(
        space=kb,
        query="q",
        candidate_file_ids=[10, 11],
        max_content=100,
        sort_by_source_and_index=False,
    )


async def test_prefilter_reaches_both_indexes_and_postfilter_removes_forbidden_chunks(monkeypatch):
    engine = RetrievalEngine(MagicMock(user_id=99), version_repo=MagicMock())
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(
            strategy="in",
            milvus_expr="document_id in [10]",
            es_filter=[{"terms": {"metadata.document_id": [10]}}],
            accessible_size=1,
        )
    )
    visibility.post_filter_retrievable_files = AsyncMock(return_value={10})
    monkeypatch.setattr(engine, "_visibility_service", lambda: visibility)

    milvus = MagicMock()
    elastic = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_engine.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=milvus),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_engine.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=elastic),
    )
    retriever = MagicMock()
    retriever.ainvoke = AsyncMock(return_value=[doc(10, "allowed"), doc(11, "forbidden-body")])
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_engine.KnowledgeRetrieverTool",
        MagicMock(return_value=retriever),
    )

    result = await engine.retrieve_and_filter(
        space=MagicMock(id=8),
        query="q",
        candidate_file_ids=None,
        max_content=100,
    )

    assert [item.page_content for item in result] == ["allowed"]
    assert milvus.as_retriever.call_args.kwargs["search_kwargs"]["expr"] == "document_id in [10]"
    assert elastic.as_retriever.call_args.kwargs["search_kwargs"]["filter"] == [
        {"terms": {"metadata.document_id": [10]}}
    ]


async def test_service_account_actor_is_not_replaced_by_compatibility_owner(monkeypatch):
    actor = PermissionActor(
        subject_type="service_account",
        subject_id=7,
        tenant_id=3,
        super_admin=False,
        tenant_admin_tenant_ids=frozenset(),
    )
    token = set_current_permission_actor(actor)
    captured = {}

    async def batch_check(login_user, **_kwargs):
        from bisheng.permission.application.identity import get_current_permission_actor

        captured["login_user"] = login_user.user_id
        captured["actor"] = get_current_permission_actor()
        return {"10": frozenset({"visible"})}

    svc = service()
    visibility = svc._visibility_service()
    visibility._non_primary_ids = AsyncMock(return_value=set())
    visibility._list_primary_file_ids_in_space = AsyncMock(return_value={10})
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service.batch_check_business_actions",
        batch_check,
    )
    try:
        result = await visibility.build_index_prefilter(8, None)
    finally:
        reset_current_permission_actor(token)

    assert result.milvus_expr == "document_id in [10]"
    assert captured == {"login_user": 99, "actor": actor}


async def test_permission_filter_failure_is_fail_closed(monkeypatch):
    engine = RetrievalEngine(MagicMock(user_id=99), version_repo=MagicMock())
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(side_effect=PermissionServiceUnavailableError())
    monkeypatch.setattr(engine, "_visibility_service", lambda: visibility)

    with pytest.raises(PermissionServiceUnavailableError):
        await engine.retrieve_and_filter(
            space=MagicMock(id=8),
            query="q",
            candidate_file_ids=None,
            max_content=100,
        )


async def test_v2_adapter_maps_permission_outage_to_503_without_chunks(monkeypatch):
    """F052 D6: the outage now surfaces as itself, not as a credential outage.

    It used to be re-raised as ``OpenApiAuthDependencyUnavailableError`` (26030
    "credential validation dependency unavailable"), which told the caller to
    look at the wrong subsystem. The transport status is still 503.
    """

    from bisheng.open_api.api.exception_handlers import open_api_http_status
    from bisheng.open_endpoints.api.endpoints.filelib import retrieve_chunks
    from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq

    monkeypatch.setattr(
        "bisheng.open_endpoints.api.endpoints.filelib.get_current_open_api_principal",
        lambda: MagicMock(
            authorization_subject_type="service_account",
            authorization_subject_id=7,
            tenant_id=1,
            actor_id=7,
            actor_name="agent",
            effective_user_id=None,
        ),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.retrieval_facade_service.RetrievalFacadeService.retrieve",
        AsyncMock(side_effect=PermissionServiceUnavailableError()),
    )

    with pytest.raises(PermissionServiceUnavailableError) as exc:
        await retrieve_chunks(
            request=MagicMock(),
            req=RetrieveReq(query="secret", knowledge_base_ids=[8]),
            version_repo=MagicMock(),
        )
    assert open_api_http_status(exc.value) == 503
    assert exc.value.code == 19002

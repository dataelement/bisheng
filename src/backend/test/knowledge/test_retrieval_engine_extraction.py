"""F052 T101a — the retrieval engine extraction keeps the chat path equivalent.

覆盖 AC: AC-19, AC-20, AC-24

``RetrievalEngine`` is the single implementation of "retrieve, then filter to
what this identity may see". ``KnowledgeSpaceChatService.aretrieve_chunks``
became a thin caller of it, and the unified facade is the second caller — so
these tests pin the two things that would silently break the arrangement:

* the engine constructs and filters **without a ``Request``** (session
  decoupling, AC-19, design 坑 4), and
* the chat service still produces exactly what the engine produces, including
  the ``document_update_time`` hydration and the permission-outage behaviour.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services import knowledge_space_chat_service as chat_mod
from bisheng.knowledge.domain.services import retrieval_engine as engine_mod
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import IndexFilter
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine


def _login_user(user_id: int = 42):
    return MagicMock(user_id=user_id)


def _doc(content: str, *, document_id: int, chunk_index: int = 0) -> Document:
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "document_name": f"{document_id}.pdf",
            "chunk_index": chunk_index,
        },
    )


def _knowledge(knowledge_id: int, knowledge_type: int):
    return MagicMock(id=knowledge_id, type=knowledge_type, user_id=7, name=f"kb-{knowledge_id}")


# ---------------------------------------------------------------------------
# AC-19 — the engine is session-decoupled: no Request anywhere in the chain
# ---------------------------------------------------------------------------


async def test_engine_constructs_without_request(monkeypatch):
    """坑 4: the visibility service takes a ``request`` it never reads."""

    engine = RetrievalEngine(_login_user())
    visibility = engine._visibility_service()

    assert visibility.request is None

    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", milvus_expr="document_id in [10]", accessible_size=1)
    )
    visibility.post_filter_retrievable_files = AsyncMock(return_value={10})
    monkeypatch.setattr(engine, "_visibility_service", lambda: visibility)
    _stub_retriever(monkeypatch, [_doc("kept", document_id=10), _doc("dropped", document_id=11)])

    docs = await engine.retrieve_and_filter(
        space=_knowledge(8, KnowledgeTypeEnum.SPACE.value),
        query="q",
        candidate_file_ids=None,
        max_content=100,
    )

    assert [doc.page_content for doc in docs] == ["kept"]


def _stub_retriever(monkeypatch, docs: list[Document]) -> MagicMock:
    retriever = MagicMock()
    retriever.ainvoke = AsyncMock(return_value=docs)
    monkeypatch.setattr(engine_mod, "KnowledgeRetrieverTool", MagicMock(return_value=retriever))
    monkeypatch.setattr(
        engine_mod.KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(engine_mod.KnowledgeRag, "init_knowledge_es_vectorstore", AsyncMock(return_value=MagicMock()))
    return retriever


# ---------------------------------------------------------------------------
# AC-20 — file-level filtering happens before anything is returned
# ---------------------------------------------------------------------------


async def test_space_path_keeps_two_layer_filter(monkeypatch):
    engine = RetrievalEngine(_login_user())
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
    _stub_retriever(monkeypatch, [_doc("allowed", document_id=10), _doc("forbidden", document_id=11)])

    docs = await engine.retrieve_and_filter(
        space=_knowledge(8, KnowledgeTypeEnum.SPACE.value),
        query="q",
        candidate_file_ids=None,
        max_content=100,
    )

    assert visibility.build_index_prefilter.await_count == 1
    assert visibility.post_filter_retrievable_files.await_count == 1
    assert [doc.page_content for doc in docs] == ["allowed"]
    assert all(doc.metadata["document_id"] != 11 for doc in docs)


async def test_space_path_skips_retrieval_when_nothing_is_visible(monkeypatch):
    engine = RetrievalEngine(_login_user())
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(return_value=IndexFilter(strategy="empty"))
    monkeypatch.setattr(engine, "_visibility_service", lambda: visibility)
    retriever = _stub_retriever(monkeypatch, [_doc("never", document_id=10)])

    docs = await engine.retrieve_and_filter(
        space=_knowledge(8, KnowledgeTypeEnum.SPACE.value),
        query="q",
        candidate_file_ids=None,
        max_content=100,
    )

    assert docs == []
    retriever.ainvoke.assert_not_awaited()


async def test_library_path_requires_use_then_filters_files(monkeypatch):
    engine = RetrievalEngine(_login_user())
    ensure_use = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service."
        "KnowledgeService.permission_service.ensure_knowledge_use_async",
        ensure_use,
    )
    engine.retrieve_and_filter = AsyncMock(return_value=[_doc("hit", document_id=10)])

    library = _knowledge(4, KnowledgeTypeEnum.NORMAL.value)
    out = await engine.retrieve_library(library, query="q", tag_names=[], max_content=100)

    ensure_use.assert_awaited_once()
    assert [(kb_id, doc.page_content) for kb_id, doc in out] == [(4, "hit")]
    engine.retrieve_and_filter.assert_awaited_once_with(
        space=library,
        query="q",
        candidate_file_ids=None,
        max_content=100,
        sort_by_source_and_index=False,
    )


async def test_library_use_denial_propagates(monkeypatch):
    engine = RetrievalEngine(_login_user())

    class _Denied(Exception):
        pass

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service."
        "KnowledgeService.permission_service.ensure_knowledge_use_async",
        AsyncMock(side_effect=_Denied()),
    )
    engine.retrieve_and_filter = AsyncMock()

    with pytest.raises(_Denied):
        await engine.retrieve_library(
            _knowledge(4, KnowledgeTypeEnum.NORMAL.value), query="q", tag_names=[], max_content=100
        )
    engine.retrieve_and_filter.assert_not_awaited()


# ---------------------------------------------------------------------------
# AC-24 — a permission outage never degrades into a narrowed result set
# ---------------------------------------------------------------------------


async def test_permission_unavailable_propagates_unchanged(monkeypatch):
    engine = RetrievalEngine(_login_user())
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(side_effect=PermissionServiceUnavailableError())
    monkeypatch.setattr(engine, "_visibility_service", lambda: visibility)

    with pytest.raises(PermissionServiceUnavailableError):
        await engine.retrieve_and_filter(
            space=_knowledge(8, KnowledgeTypeEnum.SPACE.value),
            query="q",
            candidate_file_ids=None,
            max_content=100,
        )


# ---------------------------------------------------------------------------
# AC-19 / AC-20 — chat service and engine agree, item for item
# ---------------------------------------------------------------------------


async def test_chat_service_aretrieve_chunks_delegates_to_engine(monkeypatch):
    space = _knowledge(1, KnowledgeTypeEnum.SPACE.value)
    library = _knowledge(2, KnowledgeTypeEnum.NORMAL.value)
    rows = {1: space, 2: library}
    monkeypatch.setattr(chat_mod.KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=lambda kb_id: rows.get(kb_id)))
    files = [MagicMock(id=10, update_time=None), MagicMock(id=20, update_time=None)]
    monkeypatch.setattr(engine_mod.KnowledgeFileDao, "aget_file_by_ids", AsyncMock(return_value=files))

    async def fake_retrieve_space(_self, target, **_kwargs):
        return [(target.id, _doc("space-hit", document_id=10))]

    async def fake_retrieve_library(_self, target, **_kwargs):
        return [(target.id, _doc("library-hit", document_id=20))]

    monkeypatch.setattr(RetrievalEngine, "retrieve_space", fake_retrieve_space)
    monkeypatch.setattr(RetrievalEngine, "retrieve_library", fake_retrieve_library)

    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=_login_user())
    svc.version_repo = MagicMock()
    svc._require_space_view_permission = AsyncMock()

    via_chat = await svc.aretrieve_chunks(query="q", knowledge_base_ids=[1, 2])

    engine = RetrievalEngine(_login_user(), version_repo=svc.version_repo)
    via_engine = await engine.retrieve_many([space, library], query="q", tag_filters=None, max_content=15000)
    await engine.attach_document_update_time(via_engine)

    assert [(kb_id, doc.page_content) for kb_id, doc in via_chat] == [
        (kb_id, doc.page_content) for kb_id, doc in via_engine
    ]
    assert [doc.metadata["document_update_time"] for _, doc in via_chat] == ["", ""]


async def test_chat_service_empty_ids_still_400():
    """决议-9: the in-platform chat path keeps its existing 400 contract."""

    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=_login_user())
    with pytest.raises(HTTPException) as exc:
        await svc.aretrieve_chunks(query="q", knowledge_base_ids=[])
    assert exc.value.status_code == 400


async def test_chat_service_unsupported_type_still_raises(monkeypatch):
    qa = _knowledge(3, KnowledgeTypeEnum.QA.value)
    monkeypatch.setattr(chat_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=qa))
    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=_login_user())

    with pytest.raises(chat_mod.KnowledgeTypeNotSupportedError):
        await svc.aretrieve_chunks(query="q", knowledge_base_ids=[3])


# ---------------------------------------------------------------------------
# Tag resolution and update-time hydration moved with the engine
# ---------------------------------------------------------------------------


async def test_resolve_space_file_ids_by_tags_none_when_no_tags():
    engine = RetrievalEngine(_login_user())
    assert await engine.resolve_space_file_ids_by_tags(1, []) is None


async def test_resolve_space_file_ids_by_tags_empty_when_no_tag_matches(monkeypatch):
    engine = RetrievalEngine(_login_user())
    monkeypatch.setattr(engine_mod.TagDao, "get_tags_by_business", AsyncMock(return_value=[]))
    assert await engine.resolve_space_file_ids_by_tags(1, ["unknown"]) == []


async def test_resolve_space_file_ids_by_tags_returns_file_ids(monkeypatch):
    engine = RetrievalEngine(_login_user())

    async def fake_get_tags_by_business(*, business_type, business_id, name):
        return {"alpha": [MagicMock(id=10)], "beta": [MagicMock(id=11)]}[name]

    monkeypatch.setattr(engine_mod.TagDao, "get_tags_by_business", fake_get_tags_by_business)
    monkeypatch.setattr(
        engine_mod.TagDao,
        "aget_resources_by_tags",
        AsyncMock(return_value=[MagicMock(resource_id="100"), MagicMock(resource_id="200")]),
    )

    assert sorted(await engine.resolve_space_file_ids_by_tags(1, ["alpha", "beta"])) == [100, 200]


async def test_tagged_space_with_no_matching_files_skips_retrieval(monkeypatch):
    engine = RetrievalEngine(_login_user())
    engine.resolve_space_file_ids_by_tags = AsyncMock(return_value=[])
    engine.retrieve_and_filter = AsyncMock()

    out = await engine.retrieve_space(
        _knowledge(1, KnowledgeTypeEnum.SPACE.value), query="q", tag_names=["nope"], max_content=100
    )

    assert out == []
    engine.retrieve_and_filter.assert_not_awaited()


async def test_attach_document_update_time_formats_and_defaults(monkeypatch):
    from datetime import datetime

    engine = RetrievalEngine(_login_user())
    monkeypatch.setattr(
        engine_mod.KnowledgeFileDao,
        "aget_file_by_ids",
        AsyncMock(return_value=[MagicMock(id=10, update_time=datetime(2026, 9, 16, 8, 30, 0))]),
    )

    results = [(1, _doc("a", document_id=10)), (1, _doc("b", document_id=11))]
    await engine.attach_document_update_time(results)

    assert results[0][1].metadata["document_update_time"] == "2026-09-16 08:30:00"
    assert results[1][1].metadata["document_update_time"] == ""

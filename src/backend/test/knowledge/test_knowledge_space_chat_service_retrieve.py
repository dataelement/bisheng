"""Tests for KnowledgeSpaceChatService.aretrieve_chunks / _aretrieve_chunks_for_kb.

These tests cover the multi-KB retrieval orchestration introduced for the
``POST /api/v2/filelib/retrieve`` OpenAPI endpoint. External integrations
(Milvus / ES / DB / TagDao) are mocked; we validate orchestration logic only:
filter validation, tag-name resolution, KB-not-found, multi-KB merge and
top_k truncation, and the per-chunk knowledge_id annotation.
"""
from inspect import signature
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from bisheng.developer_token.api.dependencies import get_developer_token_user
from bisheng.knowledge.domain.services import knowledge_space_chat_service as svc_mod
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.open_endpoints.api.dependencies import get_knowledge_space_chat_service_for_openapi
from bisheng.open_endpoints.api.endpoints.filelib import _build_portal_source_urls


class _StubNotFoundError(Exception):
    """Stand-in for bisheng.common.errcode.http_error.NotFoundError.

    The project's conftest pre-mocks bisheng.common.errcode.http_error as a
    MagicMock, so the real NotFoundError class is unavailable inside tests. We
    inject this real-exception substitute into svc_mod so ``raise NotFoundError``
    paths can be asserted against. Accepts the same kwargs as the real class.
    """

    def __init__(self, msg: str = "", **kwargs):
        super().__init__(msg)
        self.msg = msg


def _make_service(user_id: int = 42) -> KnowledgeSpaceChatService:
    login_user = MagicMock()
    login_user.user_id = user_id
    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=login_user)
    svc.version_repo = MagicMock()
    svc.version_repo.find_non_primary_file_ids_by_knowledge_ids = AsyncMock(return_value=[])
    svc._require_space_view_permission = AsyncMock()
    return svc


def _doc(content: str, *, document_id: int, document_name: str, chunk_index: int) -> Document:
    return Document(
        page_content=content,
        metadata={
            "document_id": document_id,
            "document_name": document_name,
            "chunk_index": chunk_index,
        },
    )


def test_build_portal_source_urls_encodes_portal_deep_link():
    source_url, source_full_url = _build_portal_source_urls(
        portal_base_url="https://portal.example.com/knowledge-spaces",
        knowledge_id=7,
        document_id=9,
    )

    assert source_url == "/knowledge-spaces?spaceId=7&fileId=9"
    assert source_full_url == "https://portal.example.com/knowledge-spaces?spaceId=7&fileId=9"


async def test_openapi_chat_service_depends_on_developer_token_user():
    params = signature(get_knowledge_space_chat_service_for_openapi).parameters
    assert params["developer_user"].default.dependency is get_developer_token_user

    request = MagicMock()
    developer_user = MagicMock()
    version_repo = MagicMock()

    service = await get_knowledge_space_chat_service_for_openapi(
        request=request,
        developer_user=developer_user,
        version_repo=version_repo,
    )

    assert service.request is request
    assert service.login_user is developer_user
    assert service.version_repo is version_repo


# ---------------------------------------------------------------------------
# aretrieve_chunks — input validation
# ---------------------------------------------------------------------------

async def test_aretrieve_chunks_empty_kb_ids_raises_400():
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.aretrieve_chunks(query="q", knowledge_base_ids=[])
    assert exc.value.status_code == 400


async def test_aretrieve_chunks_filter_references_unknown_kb_raises_400():
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.aretrieve_chunks(
            query="q",
            knowledge_base_ids=[1, 2],
            kb_filters={99: {"tags": ["t"], "tag_match_mode": "ANY"}},
        )
    assert exc.value.status_code == 400
    assert "99" in exc.value.detail


async def test_aretrieve_chunks_tag_match_mode_all_raises_400():
    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.aretrieve_chunks(
            query="q",
            knowledge_base_ids=[1],
            kb_filters={1: {"tags": ["t"], "tag_match_mode": "ALL"}},
        )
    assert exc.value.status_code == 400
    assert "ALL" in exc.value.detail


# ---------------------------------------------------------------------------
# aretrieve_chunks — orchestration (per-KB delegation mocked)
# ---------------------------------------------------------------------------

async def test_aretrieve_chunks_merges_results_and_tags_knowledge_id():
    svc = _make_service()
    svc._aretrieve_chunks_for_kb = AsyncMock(side_effect=[
        [(1, _doc("a", document_id=10, document_name="A.pdf", chunk_index=0))],
        [(2, _doc("b", document_id=20, document_name="B.pdf", chunk_index=1))],
    ])

    result = await svc.aretrieve_chunks(query="hello", knowledge_base_ids=[1, 2])

    assert [kb_id for kb_id, _ in result] == [1, 2]
    assert [d.page_content for _, d in result] == ["a", "b"]
    # Each KB delegate received its own tag_names slot (empty by default).
    calls = svc._aretrieve_chunks_for_kb.await_args_list
    assert {c.args[0] for c in calls} == {1, 2}
    for c in calls:
        assert c.kwargs["tag_names"] == []


async def test_aretrieve_chunks_truncates_to_top_k():
    svc = _make_service()
    svc._aretrieve_chunks_for_kb = AsyncMock(side_effect=[
        [(1, _doc(f"a{i}", document_id=i, document_name="A.pdf", chunk_index=i)) for i in range(3)],
        [(2, _doc(f"b{i}", document_id=i + 100, document_name="B.pdf", chunk_index=i)) for i in range(3)],
    ])

    result = await svc.aretrieve_chunks(query="hello", knowledge_base_ids=[1, 2], top_k=4)

    assert len(result) == 4
    # First three from KB 1, then one from KB 2 (concat then truncate).
    assert [kb_id for kb_id, _ in result] == [1, 1, 1, 2]


async def test_aretrieve_chunks_passes_filter_tags_to_kb_delegate():
    svc = _make_service()
    svc._aretrieve_chunks_for_kb = AsyncMock(return_value=[])

    await svc.aretrieve_chunks(
        query="hello",
        knowledge_base_ids=[7],
        kb_filters={7: {"tags": ["alpha", "beta"], "tag_match_mode": "ANY"}},
        max_content=8000,
    )

    svc._aretrieve_chunks_for_kb.assert_awaited_once()
    call = svc._aretrieve_chunks_for_kb.await_args
    assert call.args == (7,)
    assert call.kwargs["tag_names"] == ["alpha", "beta"]
    assert call.kwargs["max_content"] == 8000


# ---------------------------------------------------------------------------
# _aretrieve_chunks_for_kb — per-KB flow
# ---------------------------------------------------------------------------

async def test_aretrieve_chunks_for_kb_raises_not_found_when_space_missing(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(svc_mod, "NotFoundError", _StubNotFoundError)

    with pytest.raises(_StubNotFoundError):
        await svc._aretrieve_chunks_for_kb(
            kb_id=99, query="q", tag_names=[], max_content=15000,
        )


async def test_aretrieve_chunks_for_kb_returns_empty_when_tag_filter_resolves_to_no_files(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=MagicMock(id=1)))
    svc._resolve_kb_target_file_ids = AsyncMock(return_value=[])

    out = await svc._aretrieve_chunks_for_kb(
        kb_id=1, query="q", tag_names=["nope"], max_content=15000,
    )
    assert out == []


async def test_aretrieve_chunks_for_kb_returns_empty_when_search_kwargs_none(monkeypatch):
    """When the build helper returns (None, None) (all candidates are non-primary), skip retrieval."""
    svc = _make_service()
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=MagicMock(id=1)))
    svc._resolve_kb_target_file_ids = AsyncMock(return_value=None)
    svc._build_folder_search_kwargs = AsyncMock(return_value=(None, None))

    out = await svc._aretrieve_chunks_for_kb(
        kb_id=1, query="q", tag_names=[], max_content=15000,
    )
    assert out == []


async def test_aretrieve_chunks_for_kb_invokes_retriever_and_tags_kb_id(monkeypatch):
    svc = _make_service()
    space = MagicMock(id=1)
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    svc._resolve_kb_target_file_ids = AsyncMock(return_value=None)
    svc._build_folder_search_kwargs = AsyncMock(return_value=({"k": 100}, {"k": 100}))

    milvus_store = MagicMock()
    milvus_store.as_retriever.return_value = MagicMock()
    es_store = MagicMock()
    es_store.as_retriever.return_value = MagicMock()
    monkeypatch.setattr(
        svc_mod.KnowledgeRag,
        "init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=milvus_store),
    )
    monkeypatch.setattr(
        svc_mod.KnowledgeRag,
        "init_knowledge_es_vectorstore",
        AsyncMock(return_value=es_store),
    )

    docs = [
        _doc("hit-1", document_id=10, document_name="A.pdf", chunk_index=0),
        _doc("hit-2", document_id=10, document_name="A.pdf", chunk_index=1),
    ]
    fake_tool = MagicMock()
    fake_tool.ainvoke = AsyncMock(return_value=docs)
    tool_factory = MagicMock(return_value=fake_tool)
    monkeypatch.setattr(svc_mod, "KnowledgeRetrieverTool", tool_factory)

    out = await svc._aretrieve_chunks_for_kb(
        kb_id=1, query="hello", tag_names=[], max_content=12345,
    )

    assert [kb_id for kb_id, _ in out] == [1, 1]
    assert [d.page_content for _, d in out] == ["hit-1", "hit-2"]
    # KnowledgeRetrieverTool constructed with the requested max_content
    assert tool_factory.call_args.kwargs["max_content"] == 12345
    fake_tool.ainvoke.assert_awaited_once_with("hello")


# ---------------------------------------------------------------------------
# _resolve_kb_target_file_ids — tag name → id → file id mapping
# ---------------------------------------------------------------------------

async def test_resolve_kb_target_file_ids_none_when_no_tags():
    svc = _make_service()
    assert await svc._resolve_kb_target_file_ids(1, []) is None


async def test_resolve_kb_target_file_ids_empty_when_no_tag_matches(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc_mod.TagDao, "get_tags_by_business", AsyncMock(return_value=[]))
    out = await svc._resolve_kb_target_file_ids(1, ["unknown-tag"])
    assert out == []


async def test_resolve_kb_target_file_ids_returns_file_ids(monkeypatch):
    svc = _make_service()
    tag_a = MagicMock(id=10)
    tag_b = MagicMock(id=11)

    async def fake_get_tags_by_business(*, business_type, business_id, name):
        return {"alpha": [tag_a], "beta": [tag_b]}[name]

    monkeypatch.setattr(svc_mod.TagDao, "get_tags_by_business", fake_get_tags_by_business)
    monkeypatch.setattr(
        svc_mod.TagDao,
        "aget_resources_by_tags",
        AsyncMock(return_value=[
            MagicMock(resource_id="100"),
            MagicMock(resource_id="200"),
        ]),
    )

    out = await svc._resolve_kb_target_file_ids(1, ["alpha", "beta"])
    assert sorted(out) == [100, 200]

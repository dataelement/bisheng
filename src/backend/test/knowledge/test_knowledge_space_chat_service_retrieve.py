"""Tests for KnowledgeSpaceChatService.aretrieve_chunks.

These tests cover the multi-KB retrieval orchestration introduced for the
``POST /api/v2/filelib/retrieve`` OpenAPI endpoint. External integrations
(Milvus / ES / DB / TagDao) are mocked; we validate orchestration logic only:
filter validation, KB-not-found, multi-KB merge and top_k truncation, and the
per-chunk knowledge_id annotation.

F052 T101 moved the retrieval itself into ``RetrievalEngine``; what stays on
the chat service is this path's own contract (the 400s, the existence / type
verdict, the space-level gate). Tag-name resolution and the two-layer filter
loop are now covered by ``test_retrieval_engine_extraction.py``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services import knowledge_space_chat_service as svc_mod
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


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
    engine = MagicMock()
    engine.attach_document_update_time = AsyncMock()
    svc._knowledge_retrieval_engine = engine
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
    svc._aretrieve_chunks_for_one = AsyncMock(
        side_effect=[
            [(1, _doc("a", document_id=10, document_name="A.pdf", chunk_index=0))],
            [(2, _doc("b", document_id=20, document_name="B.pdf", chunk_index=1))],
        ]
    )

    result = await svc.aretrieve_chunks(query="hello", knowledge_base_ids=[1, 2])

    assert [kb_id for kb_id, _ in result] == [1, 2]
    assert [d.page_content for _, d in result] == ["a", "b"]
    # Each KB delegate received its own tag_names slot (empty by default).
    calls = svc._aretrieve_chunks_for_one.await_args_list
    assert {c.args[1] for c in calls} == {1, 2}
    for call in calls:
        assert call.kwargs["tag_names"] == []


async def test_aretrieve_chunks_truncates_to_top_k():
    svc = _make_service()
    svc._aretrieve_chunks_for_one = AsyncMock(
        side_effect=[
            [(1, _doc(f"a{i}", document_id=i, document_name="A.pdf", chunk_index=i)) for i in range(3)],
            [(2, _doc(f"b{i}", document_id=i + 100, document_name="B.pdf", chunk_index=i)) for i in range(3)],
        ]
    )

    result = await svc.aretrieve_chunks(query="hello", knowledge_base_ids=[1, 2], top_k=4)

    assert len(result) == 4
    # First three from KB 1, then one from KB 2 (concat then truncate).
    assert [kb_id for kb_id, _ in result] == [1, 1, 1, 2]


async def test_aretrieve_chunks_passes_filter_tags_to_kb_delegate():
    svc = _make_service()
    svc._aretrieve_chunks_for_one = AsyncMock(return_value=[])

    await svc.aretrieve_chunks(
        query="hello",
        knowledge_base_ids=[7],
        kb_filters={7: {"tags": ["alpha", "beta"], "tag_match_mode": "ANY"}},
        max_content=8000,
    )

    svc._aretrieve_chunks_for_one.assert_awaited_once()
    call = svc._aretrieve_chunks_for_one.await_args
    assert call.args[1] == 7
    assert call.kwargs["tag_names"] == ["alpha", "beta"]
    assert call.kwargs["max_content"] == 8000


# ---------------------------------------------------------------------------
# _aretrieve_chunks_for_one — existence, type verdict and the space gate
# ---------------------------------------------------------------------------


async def test_aretrieve_chunks_for_one_raises_not_found_when_missing(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(svc_mod, "NotFoundError", _StubNotFoundError)

    with pytest.raises(_StubNotFoundError):
        await svc._aretrieve_chunks_for_one(MagicMock(), 99, query="q", tag_names=[], max_content=15000)


async def test_aretrieve_chunks_for_one_space_checks_gate_then_delegates(monkeypatch):
    svc = _make_service()
    space = MagicMock(id=1, type=KnowledgeTypeEnum.SPACE.value)
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    engine = MagicMock()
    engine.retrieve_space = AsyncMock(
        return_value=[(1, _doc("hit", document_id=10, document_name="A.pdf", chunk_index=0))]
    )

    out = await svc._aretrieve_chunks_for_one(engine, 1, query="hello", tag_names=[], max_content=12345)

    svc._require_space_view_permission.assert_awaited_once_with(1)
    engine.retrieve_space.assert_awaited_once_with(space, query="hello", tag_names=[], max_content=12345)
    assert [(kb_id, doc.page_content) for kb_id, doc in out] == [(1, "hit")]


async def test_aretrieve_chunks_for_one_library_skips_space_gate(monkeypatch):
    svc = _make_service()
    library = MagicMock(id=4, type=KnowledgeTypeEnum.NORMAL.value)
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=library))
    engine = MagicMock()
    engine.retrieve_library = AsyncMock(return_value=[])

    await svc._aretrieve_chunks_for_one(engine, 4, query="q", tag_names=["t"], max_content=100)

    svc._require_space_view_permission.assert_not_awaited()
    engine.retrieve_library.assert_awaited_once_with(library, query="q", tag_names=["t"], max_content=100)


async def test_aretrieve_chunks_for_one_rejects_unsupported_type(monkeypatch):
    svc = _make_service()
    qa = MagicMock(id=5, type=KnowledgeTypeEnum.QA.value)
    monkeypatch.setattr(svc_mod.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=qa))

    with pytest.raises(svc_mod.KnowledgeTypeNotSupportedError):
        await svc._aretrieve_chunks_for_one(MagicMock(), 5, query="q", tag_names=[], max_content=100)

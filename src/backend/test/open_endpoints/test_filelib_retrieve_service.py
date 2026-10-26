import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq
from bisheng.open_endpoints.domain.services.filelib_retrieve_service import FilelibRetrieveService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import RetrieveSourceLink, RetrieveSourceRef


@pytest.mark.parametrize("denied", [False, True])
async def test_shared_retrieval_only_resolves_sources_after_authorization(denied):
    """AC-06, AC-07, AC-11: ordered results and canonical source references are shared."""
    doc = Document(
        page_content="authorized",
        metadata={
            "document_id": 7,
            "document_name": "name",
            "chunk_index": 3,
            "canonical_document_id": 8,
            "canonical_version_id": 9,
        },
    )
    chat = SimpleNamespace(
        aretrieve_chunks=AsyncMock(
            return_value=[(118, doc), (118, doc)],
            side_effect=HTTPException(403) if denied else None,
        )
    )
    source = SimpleNamespace(resolve_links=AsyncMock(return_value={7: RetrieveSourceLink("/source", "https://source")}))
    service = FilelibRetrieveService(
        chat,
        source,
        SimpleNamespace(
            config=SimpleNamespace(
                total_timeout_seconds=1,
                source_link_timeout_seconds=0.1,
            )
        ),
    )
    req = RetrieveReq(query="q", knowledge_base_ids=[118])
    if denied:
        with pytest.raises(HTTPException):
            await service.retrieve(req)
        source.resolve_links.assert_not_awaited()
    else:
        result = await service.retrieve(req)
        assert result.total == 2
        assert result.chunks[0].document_id == 7
        assert result.chunks[0].source_full_url == "https://source"
        source.resolve_links.assert_awaited_once_with([RetrieveSourceRef(7, 8, 9)])


async def test_source_deadline_keeps_authorized_chunks_without_link():
    """AC-09, AC-11: keep the existing source-timeout degradation policy."""

    async def delayed(refs):
        await asyncio.sleep(1)

    chat = SimpleNamespace(
        aretrieve_chunks=AsyncMock(
            return_value=[
                (118, Document(page_content="authorized", metadata={"document_id": 7})),
            ]
        )
    )
    service = FilelibRetrieveService(
        chat,
        SimpleNamespace(resolve_links=delayed),
        SimpleNamespace(config=SimpleNamespace(total_timeout_seconds=1, source_link_timeout_seconds=0.001)),
    )
    result = await service.retrieve(RetrieveReq(query="q", knowledge_base_ids=[118]))
    assert result.chunks[0].content == "authorized"
    assert result.chunks[0].source_full_url == ""


def scoped_service(document_id=7):
    chat = SimpleNamespace(
        aretrieve_chunks=AsyncMock(
            return_value=[
                (118, Document(page_content="authorized", metadata={"document_id": document_id})),
            ]
        )
    )
    source = SimpleNamespace(resolve_links=AsyncMock(return_value={}))
    service = FilelibRetrieveService(
        chat,
        source,
        SimpleNamespace(config=SimpleNamespace(total_timeout_seconds=1, source_link_timeout_seconds=1)),
    )
    return service, chat, source


@pytest.mark.parametrize("scope", [None, {118: []}, {118: [7]}])
async def test_internal_file_scope_preserves_three_states_and_tags(scope):
    """F083 覆盖 AC: AC-03, AC-05, AC-06, AC-07;空集不能退化为整库。"""
    service, chat, source = scoped_service()
    req = RetrieveReq(
        query="q",
        knowledge_base_ids=[118],
        filters={
            "knowledge_base_filters": [{"knowledge_base_id": 118, "tags": ["policy"]}],
        },
    )
    original = req.model_dump()
    result = await service.retrieve(req, **({"file_ids_by_knowledge": scope} if scope is not None else {}))
    if scope == {118: []}:
        assert result.total == 0 and not result.chunks
        chat.aretrieve_chunks.assert_not_called()
        source.resolve_links.assert_not_called()
    else:
        assert result.total == 1
        kwargs = chat.aretrieve_chunks.await_args.kwargs
        assert kwargs["kb_filters"][118]["tags"] == ["policy"]
        if scope is None:
            assert "strict_file_scope" not in kwargs
            assert "file_ids" not in kwargs["kb_filters"][118]
        else:
            assert kwargs["strict_file_scope"] is True
            assert kwargs["kb_filters"][118]["file_ids"] == [7]
    assert req.model_dump() == original


@pytest.mark.parametrize("scope", [{}, {119: [7]}, {118: [True]}, {118: [0]}, {118: ["7"]}])
async def test_invalid_internal_scope_never_reaches_search(scope):
    """F083 覆盖 AC: AC-05, AC-06;内部装配丢失或错误范围也必须失败。"""
    service, chat, source = scoped_service()
    with pytest.raises(ValueError):
        await service.retrieve(RetrieveReq(query="q", knowledge_base_ids=[118]), file_ids_by_knowledge=scope)
    chat.aretrieve_chunks.assert_not_called()
    source.resolve_links.assert_not_called()


async def test_out_of_scope_result_is_rejected_before_signing_source():
    """F083 覆盖 AC: AC-05;目录外入口不得签发来源或返回正文。"""
    service, _, source = scoped_service(document_id=8)
    with pytest.raises(ValueError):
        await service.retrieve(RetrieveReq(query="q", knowledge_base_ids=[118]), file_ids_by_knowledge={118: [7]})
    source.resolve_links.assert_not_called()

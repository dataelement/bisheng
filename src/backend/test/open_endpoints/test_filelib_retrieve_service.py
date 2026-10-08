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

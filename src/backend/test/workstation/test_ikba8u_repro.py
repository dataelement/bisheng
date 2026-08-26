"""Reproduction test for the IKBA8U bug.

The bug report: "日常模式-检索知识空间，只有知识空间权限，没有知识空间下的文件权限。检索出来了"
(Daily mode - search knowledge space. User only has knowledge space permission
but no file-level permission. The search still returns those files.)

This test exercises the full queryChunksFromDB path with a user that has
view_space but no view_file on any file in the space. The expectation is that
NO files are returned.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam


def _make_doc(file_id: int, content: str = "", knowledge_id: int = 100) -> Document:
    return Document(
        page_content=content or f"chunk-{file_id}",
        metadata={
            "document_id": file_id,
            "document_name": f"doc-{file_id}.txt",
            "knowledge_id": knowledge_id,
        },
    )


@pytest.mark.asyncio
async def test_query_chunks_space_kb_with_view_space_only_returns_no_docs(monkeypatch):
    """A user with only view_space (no per-file view_file, no membership, not public)
    must get an empty result list from queryChunksFromDB.

    Reproduces the IKBA8U bug: files in the space were leaked into AI Q&A
    retrieval even though the user did not hold any view_file binding.
    """

    # 1. is_space_visible: user has view_space → True
    async def fake_is_space_visible(self, space_id: int) -> bool:
        return True

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.is_space_visible",
        fake_is_space_visible,
    )

    # 2. post_filter_visible_files: user has NO view_file → empty
    async def fake_post_filter(self, space_id, file_ids):
        return set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post_filter,
    )

    # 3. Vector store returns docs that look like real chunks
    async def fake_get_vectorstore(**kwargs):
        return {
            100: {
                "knowledge": SimpleNamespace(id=100, name="space-100"),
                "milvus": object(),
                "es": None,
            }
        }

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.KnowledgeRag.get_multi_knowledge_vectorstore",
        fake_get_vectorstore,
    )

    class FakeKnowledgeRetrieverTool:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, payload):
            # Return 3 chunks — without the post-filter these would all leak
            return [_make_doc(1, "chunk-1"), _make_doc(2, "chunk-2"), _make_doc(3, "chunk-3")]

    class FakeMultiRetriever:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.KnowledgeRetrieverTool",
        FakeKnowledgeRetrieverTool,
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.MultiRetriever",
        FakeMultiRetriever,
    )

    login_user = MagicMock(user_id=42, user_name="bob")
    login_user.is_admin = MagicMock(return_value=False)

    formatted, docs, failures = await WorkStationService.queryChunksFromDB(
        question="related question",
        use_knowledge_param=UseKnowledgeBaseParam(knowledge_space_ids=[100]),
        max_token=1000,
        login_user=login_user,
    )

    # Expected: 0 docs returned because user lacks view_file
    assert docs == [], f"Expected no docs; got {docs!r} — IKBA8U regression"
    assert formatted == [], f"Expected no formatted results; got {formatted!r}"

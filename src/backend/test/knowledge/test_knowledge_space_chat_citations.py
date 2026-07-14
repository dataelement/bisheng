from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)


@pytest.mark.asyncio
async def test_prepare_rag_citation_context_contains_real_chunk_id(monkeypatch):
    service = KnowledgeSpaceChatService(request=MagicMock(), login_user=MagicMock())
    document = Document(
        page_content=("{<file_title>report.pdf</file_title>\n<paragraph_content>retrieved body</paragraph_content>}"),
        metadata={
            "knowledge_id": 10,
            "document_id": 42,
            "document_name": "report.pdf",
            "chunk_index": 3,
        },
    )
    cache_mock = AsyncMock()
    monkeypatch.setattr(
        CitationRegistryService,
        "generate_rag_citation_id",
        classmethod(lambda cls: "knowledgesearch_current"),
    )
    monkeypatch.setattr(
        CitationRegistryService,
        "_load_knowledge_names",
        classmethod(lambda cls, documents: {10: "Test Space"}),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.cache_citation_registry_items",
        cache_mock,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeUtils.format_retrieved_chunk",
        lambda doc: (
            f"<chunk_id>{doc.metadata['citation_key']}</chunk_id>\n"
            f"<file_title>{doc.metadata['document_name']}</file_title>\n"
            "<paragraph_content>retrieved body</paragraph_content>"
        ),
        raising=False,
    )

    context, citation_items = await service._prepare_rag_citation_context([document])

    assert "<chunk_id>knowledgesearch_current:3</chunk_id>" in context
    assert "<file_title>report.pdf</file_title>" in context
    assert "<paragraph_content>retrieved body</paragraph_content>" in context
    assert [item.key for item in citation_items] == ["knowledgesearch_current:3"]
    cache_mock.assert_awaited_once_with(citation_items)

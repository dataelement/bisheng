"""F062 T011 — annotate / collect temp chunks, mix with RAG, failure fallback."""

from unittest.mock import patch

from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import CitationType
from bisheng.citation.domain.services.citation_prompt_helper import (
    _is_citable_rag_document,
    _is_temp_file_document,
    annotate_rag_documents_with_citations,
    annotate_temp_documents_with_citations,
    collect_rag_citation_registry_items,
    collect_temp_citation_registry_items,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService


def _temp_doc(document_id: str = "3f2a1c9e8b7d4f6a") -> Document:
    return Document(
        page_content="临时切片",
        metadata={
            "document_id": document_id,
            "knowledge_id": "wf-01H9Z",
            "document_name": "报价单.pdf",
            "source_url": "https://minio.example/tmp/报价单.pdf",
            "chunk_index": 0,
        },
    )


def _rag_doc() -> Document:
    return Document(
        page_content="知识库切片",
        metadata={"document_id": 7, "knowledge_id": 1, "document_name": "制度.pdf", "chunk_index": 0},
    )


def test_annotate_temp_issues_tempsearch_key():
    annotated = annotate_temp_documents_with_citations([_temp_doc()])
    key = annotated[0].metadata.get("citation_key")
    assert key
    assert key.startswith("tempsearch_")
    assert "citation_key:" in annotated[0].page_content


def test_collect_temp_registry_is_temp_type():
    annotated = annotate_temp_documents_with_citations([_temp_doc()])
    items = collect_temp_citation_registry_items(annotated)
    assert items
    assert items[0].type == CitationType.TEMP
    assert items[0].citationId.startswith(CitationRegistryService.TEMP_PREFIX)


def test_mix_integer_goes_rag_uuid_goes_temp():
    mixed = [_rag_doc(), _temp_doc()]
    with patch.object(CitationRegistryService, "_load_knowledge_names", return_value={}):
        rag_annotated = annotate_rag_documents_with_citations(mixed)
        rag_items = collect_rag_citation_registry_items(rag_annotated)
    temp_annotated = annotate_temp_documents_with_citations(mixed)
    temp_items = collect_temp_citation_registry_items(temp_annotated)
    assert all(item.type == CitationType.RAG for item in rag_items)
    assert all(item.type == CitationType.TEMP for item in temp_items)
    assert rag_items
    assert temp_items


def test_uuid_still_rejected_as_rag():
    assert _is_citable_rag_document(_temp_doc()) is False
    assert _is_temp_file_document(_temp_doc()) is True
    assert _is_temp_file_document(_rag_doc()) is False


def test_annotate_temp_swallows_registry_failure():
    with patch.object(CitationRegistryService, "build_temp_registry", side_effect=RuntimeError("boom")):
        annotated = annotate_temp_documents_with_citations([_temp_doc()])
    assert annotated[0].page_content == "临时切片"
    assert "citation_key" not in annotated[0].metadata

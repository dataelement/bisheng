"""F062 T006 — temporary-knowledge-base citation registry.

RED until T007 lands ``build_temp_registry`` / ``TEMP_PREFIX`` / the temp
load and group branches.
"""

from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import CitationType, TempCitationPayloadSchema
from bisheng.citation.domain.services.citation_prompt_helper import _is_citable_rag_document
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService


def _temp_doc(document_id: str = "3f2a1c9e8b7d4f6a", name: str = "报价单.pdf") -> Document:
    return Document(
        page_content="临时知识库切片",
        metadata={
            "document_id": document_id,
            "knowledge_id": "wf-01H9Z",
            "document_name": name,
            "source_url": "https://minio.example/tmp/报价单.pdf",
            "chunk_index": 0,
        },
    )


def test_build_temp_registry_uses_temp_type_and_prefix():
    items = CitationRegistryService.build_temp_registry([_temp_doc()])
    assert len(items) == 1
    item = items[0]
    assert item.type == CitationType.TEMP
    assert item.citationId.startswith(CitationRegistryService.TEMP_PREFIX)
    assert item.citationId.startswith("tempsearch_")


def test_temp_payload_has_uuid_document_id_not_integers():
    items = CitationRegistryService.build_temp_registry([_temp_doc()])
    payload = items[0].sourcePayload
    assert isinstance(payload, TempCitationPayloadSchema)
    assert payload.documentId == "3f2a1c9e8b7d4f6a"
    dumped = payload.model_dump()
    assert "knowledgeId" not in dumped
    assert not isinstance(dumped.get("documentId"), int)


def test_temp_payload_round_trips_through_load():
    items = CitationRegistryService.build_temp_registry([_temp_doc()])
    dumped = CitationRegistryService.dump_source_payload(items[0].sourcePayload)
    loaded = CitationRegistryService._load_source_payload(CitationType.TEMP.value, dumped)
    assert loaded["documentId"] == "3f2a1c9e8b7d4f6a"
    assert loaded["documentName"] == "报价单.pdf"
    assert "url" not in loaded


def test_load_temp_does_not_fall_through_to_web_schema():
    dumped = {
        "documentId": "abc123",
        "documentName": "a.pdf",
        "items": [{"itemId": "0", "content": "x"}],
    }
    loaded = CitationRegistryService._load_source_payload("temp", dumped)
    assert loaded["documentId"] == "abc123"
    assert "url" not in loaded


def test_two_files_become_two_citations():
    docs = [_temp_doc("id-one", "a.pdf"), _temp_doc("id-two", "b.pdf")]
    items = CitationRegistryService.build_temp_registry(docs)
    citation_ids = {item.citationId for item in items}
    document_ids = {item.sourcePayload.documentId for item in items}
    assert len(citation_ids) == 2
    assert document_ids == {"id-one", "id-two"}


def test_uuid_document_is_still_not_citable_as_rag():
    assert _is_citable_rag_document(_temp_doc()) is False

"""F062 T003 — non-regression baseline for the citation spine.

Written against the code BEFORE F062 opens temporary-knowledge-base
citations. T024 re-runs this file once every F062 task has landed; both
runs must be green.

Locks three things F062 promises not to disturb:

- AC-12  UUID documents still cannot be registered as RAG; integer
         document ids still can. Official knowledge / article / web paths
         are not rewritten here (see test_f054_non_regression.py and
         test_access_scope_tiering.py — T024 re-runs those too).
- AC-21  unregistered markers are stripped; leftover user-visible text
         must not contain internal citation keys or protocol characters.
- AC-24  this file does not invent a backfill of structured citations onto
         historical messages. Absence of a backfill helper is the lock.

Do NOT assert "temp sources produce no badges" here — that was F054's
target and T013 rewrites it.
"""

from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_START_MARKER,
    _is_citable_rag_document,
    strip_unregistered_citation_markers,
)
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService


def _uuid_doc() -> Document:
    return Document(
        page_content="临时知识库切片",
        metadata={
            "document_id": "3f2a1c9e8b7d4f6a",
            "knowledge_id": "wf-01H9Z",
            "document_name": "报价单.pdf",
        },
    )


def _web_item() -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId="websearch_abcd1234",
        type=CitationType.WEB,
        sourcePayload=WebCitationPayloadSchema(url="https://example.com", title="Example"),
    )


def test_uuid_document_is_still_not_citable_as_rag():
    assert _is_citable_rag_document(_uuid_doc()) is False


def test_integer_document_id_is_still_citable_as_rag():
    document = Document(page_content="正文", metadata={"document_id": 7, "knowledge_id": 1})
    assert _is_citable_rag_document(document) is True


def test_anonymous_readable_is_web_only():
    assert CitationResolveService._is_anonymous_readable(_web_item()) is True
    for citation_type in (CitationType.RAG, CitationType.ARTICLE, CitationType.TEMP):
        item = _web_item().model_copy(update={"type": citation_type})
        assert CitationResolveService._is_anonymous_readable(item) is False


def test_unregistered_internal_keys_are_stripped_from_visible_text():
    text = f"结论{CITATION_START_MARKER}tempsearch_deadbeef:0{CITATION_END_MARKER}完毕"
    stripped = strip_unregistered_citation_markers(text, items=[])
    assert "tempsearch_" not in stripped
    assert "knowledgesearch_" not in stripped
    assert CITATION_START_MARKER not in stripped
    assert CITATION_END_MARKER not in stripped
    assert stripped == "结论完毕"

"""Only in-answer citation markers become called knowledge files."""

from pathlib import Path

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    portal_answer_called_file_ids,
    referenced_rag_file_ids,
    select_registry_items_for_persistence,
)

MARKED = "结论见\ue200cite-a:chunk-1\ue201cite-a:chunk-2\ue202。"


def _rag(citation_id: str, document_id: int | None) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        key=f"{citation_id}:chunk-1",
        sourcePayload=RagCitationPayloadSchema(
            documentId=document_id,
            documentName="制度",
            items=[RagCitationItemSchema(itemId="chunk-1")],
        ),
    )


def test_marked_answer_keeps_distinct_positive_file_ids_only():
    items = [
        _rag("cite-a", 42),
        _rag("cite-a", 42),
        _rag("cite-b", 7),
        _rag("cite-c", 0),
        CitationRegistryItemSchema(
            citationId="web-1",
            type=CitationType.WEB,
            key="web-1:page",
            sourcePayload=WebCitationPayloadSchema(url="https://example.test/a"),
        ),
    ]
    text = "\ue200cite-a:chunk-1\ue202 and \ue200cite-b:chunk-1\ue201cite-c:chunk-1\ue202 plus \ue200web-1:page\ue202"
    assert referenced_rag_file_ids(items, text) == [42, 7]


def test_only_successful_portal_answers_contribute_called_files():
    items = [_rag("cite-a", 42)]
    assert portal_answer_called_file_ids(
        portal_context=True,
        answer_failed=False,
        items=items,
        text=MARKED,
    ) == [42]
    assert (
        portal_answer_called_file_ids(
            portal_context=False,
            answer_failed=False,
            items=items,
            text=MARKED,
        )
        == []
    )
    assert (
        portal_answer_called_file_ids(
            portal_context=True,
            answer_failed=True,
            items=items,
            text=MARKED,
        )
        == []
    )
    assert (
        portal_answer_called_file_ids(
            portal_context=True,
            answer_failed=False,
            items=items,
            text="没有引用标记",
        )
        == []
    )


def test_chat_enqueues_citations_only_after_the_answer_is_saved():
    source = Path("bisheng/workstation/domain/services/chat_service.py").read_text()
    save_at = source.index("await save_message_citations(")
    enqueue_at = source.index("enqueue_portal_qa_citations_async")
    assert save_at < enqueue_at
    assert "portal_answer_called_file_ids" in source
    assert "RealtimeQaQuestionFact" not in source[save_at:enqueue_at]


def test_unmarked_answer_contributes_no_called_files_but_still_persists_citations():
    items = [_rag("cite-a", 42)]
    assert referenced_rag_file_ids(items, "没有引用标记") == []
    assert select_registry_items_for_persistence(items, "没有引用标记") == items
    assert referenced_rag_file_ids(items, MARKED) == [42]

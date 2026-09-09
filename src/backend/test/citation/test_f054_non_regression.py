"""F054 T002 — non-regression baseline for the citation spine.

Written and green against the code as it stands BEFORE F054 changes anything.
That ordering is the whole point: a regression suite authored after the edit
only restates the new behaviour and cannot show that nothing moved. T014
re-runs this file once every F054 task has landed; both runs must be green.

Locks four things F054 promises not to disturb:

- AC-07  conversation export keeps stripping citations (the user decided
         against baking visible numbers, so the strip must not quietly become
         a bake).
- AC-12  internal citation keys never survive into user-visible text.
- AC-18  the shared annotate/collect/select spine behind all four live entry
         points (workflow, daily chat, assistant, knowledge space) is unchanged
         — including the "no markers in the answer ⇒ keep every item" fallback
         that F054 deliberately does NOT use for articles (design §3 decision 4).
- AC-21/22 citations bind to the message id they are handed, so a regenerated
         answer gets its own binding rather than inheriting the previous one.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.documents import Document

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_SEPARATOR_MARKER,
    CITATION_START_MARKER,
    annotate_rag_documents_with_citations,
    collect_rag_citation_registry_items,
    extract_citation_ids_from_text,
    select_registry_items_for_persistence,
    strip_unregistered_citation_markers,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.workstation.domain.services.conversation_export_service import ConversationExportService


def _marker(*keys: str) -> str:
    return CITATION_START_MARKER + CITATION_SEPARATOR_MARKER.join(keys) + CITATION_END_MARKER


def _kb_doc() -> Document:
    return Document(
        page_content="正文",
        metadata={"document_id": 7, "knowledge_id": 1, "chunk_index": 0, "document_name": "a.pdf"},
    )


# Knowledge display names are a DB read behind a tenant ContextVar; these tests
# assert marker plumbing, not naming, so the batch lookup is stubbed out.
_no_knowledge_names = patch.object(CitationRegistryService, "_load_knowledge_names", return_value={})


def _rag_item(citation_id: str, document_id: int = 7) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=1,
            documentId=document_id,
            documentName=f"file-{document_id}.pdf",
            items=[RagCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


# --------------------------------------------------------------------------- #
# AC-07 — conversation export still strips, never bakes
# --------------------------------------------------------------------------- #


def test_export_strips_well_formed_markers():
    text = "结论一。" + _marker("knowledgesearch_ab12cd34:0") + "结论二。"
    stripped = ConversationExportService._strip_citations(text)

    assert stripped == "结论一。结论二。"
    for marker in (CITATION_START_MARKER, CITATION_SEPARATOR_MARKER, CITATION_END_MARKER):
        assert marker not in stripped


def test_export_strips_multi_source_markers_and_lone_markers():
    text = (
        "多来源。"
        + _marker("knowledgesearch_ab12cd34:0", "websearch_ff001122:1")
        + "半截标记"
        + CITATION_START_MARKER
        + "结尾。"
    )
    stripped = ConversationExportService._strip_citations(text)

    assert "knowledgesearch_" not in stripped
    assert "websearch_" not in stripped
    assert CITATION_START_MARKER not in stripped


def test_export_strips_bare_citation_keys_without_markers():
    """The naked-key fallback exists because the front-end has been seen
    rendering U+E200 as a literal glyph, leaving the key unwrapped."""
    stripped = ConversationExportService._strip_citations("裸键 knowledgesearch_ab12cd34:0 尾巴")

    assert "knowledgesearch_" not in stripped


def test_export_never_adds_a_reference_section():
    """F054 explicitly does NOT bake: no ordinal, no 参考资料 section."""
    text = "结论。" + _marker("knowledgesearch_ab12cd34:0")
    stripped = ConversationExportService._strip_citations(text)

    assert "参考资料" not in stripped
    assert "[1]" not in stripped


def test_export_leaves_plain_text_untouched():
    assert ConversationExportService._strip_citations("没有任何角标的答案。") == "没有任何角标的答案。"
    assert ConversationExportService._strip_citations("") == ""


# --------------------------------------------------------------------------- #
# AC-12 — internal keys never reach user-visible text
# --------------------------------------------------------------------------- #


def test_unregistered_markers_are_removed_registered_ones_survive():
    known = _rag_item("knowledgesearch_ab12cd34")
    text = "真来源。" + _marker("knowledgesearch_ab12cd34:0") + "假来源。" + _marker("knowledgesearch_bixude.mp4:0")

    scrubbed = strip_unregistered_citation_markers(text, [known])

    assert "bixude.mp4" not in scrubbed
    assert "knowledgesearch_ab12cd34:0" in scrubbed


def test_partially_known_marker_keeps_only_the_known_ids():
    known = _rag_item("knowledgesearch_ab12cd34")
    text = "混合。" + _marker("knowledgesearch_ab12cd34:0", "knowledgesearch_deadbeef:1")

    scrubbed = strip_unregistered_citation_markers(text, [known])

    assert "knowledgesearch_ab12cd34:0" in scrubbed
    assert "knowledgesearch_deadbeef" not in scrubbed


def test_text_without_markers_is_returned_unchanged():
    assert strip_unregistered_citation_markers("纯文本", []) == "纯文本"


# --------------------------------------------------------------------------- #
# AC-18 — the shared spine behind all four live entry points
# --------------------------------------------------------------------------- #


def test_annotate_appends_citation_key_to_content_and_metadata():
    documents = [_kb_doc()]

    with _no_knowledge_names:
        annotated = annotate_rag_documents_with_citations(documents)

    citation_key = annotated[0].metadata["citation_key"]
    assert citation_key.startswith(CitationRegistryService.RAG_PREFIX)
    assert annotated[0].page_content.endswith(f"citation_key: {citation_key}")
    # The caller's documents must not be mutated in place.
    assert "citation_key" not in documents[0].metadata


def test_documents_without_metadata_get_no_citation_key():
    with _no_knowledge_names:
        annotated = annotate_rag_documents_with_citations([Document(page_content="裸文档", metadata={})])

    assert "citation_key" not in annotated[0].metadata
    assert annotated[0].page_content == "裸文档"


def test_collect_strips_the_citation_key_tail_back_out_of_content():
    with _no_knowledge_names:
        items = collect_rag_citation_registry_items(annotate_rag_documents_with_citations([_kb_doc()]))

    assert len(items) == 1
    assert items[0].type == CitationType.RAG
    assert items[0].accessScope == "per_user"
    assert "citation_key:" not in (items[0].sourcePayload.items[0].content or "")


def test_select_for_persistence_keeps_only_referenced_items():
    referenced, unreferenced = _rag_item("knowledgesearch_ab12cd34"), _rag_item("knowledgesearch_deadbeef", 8)
    answer = "用了第一条。" + _marker("knowledgesearch_ab12cd34:0")

    kept = select_registry_items_for_persistence([referenced, unreferenced], answer)

    assert [i.citationId for i in kept] == ["knowledgesearch_ab12cd34"]


def test_select_for_persistence_falls_back_to_everything_when_no_marker():
    """The retrieval entry points rely on this fallback. F054's article path
    deliberately does not (design §3 decision 4) — but the fallback itself must
    stay put for the four live entries."""
    items = [_rag_item("knowledgesearch_ab12cd34"), _rag_item("knowledgesearch_deadbeef", 8)]

    assert select_registry_items_for_persistence(items, "模型一个标记都没发。") == items


def test_extract_citation_ids_reads_every_id_in_a_multi_source_marker():
    text = "多来源。" + _marker("knowledgesearch_ab12cd34:0", "websearch_ff001122:1")

    assert extract_citation_ids_from_text(text) == {"knowledgesearch_ab12cd34", "websearch_ff001122"}


# --------------------------------------------------------------------------- #
# AC-21 / AC-22 — citations bind to the message id they are handed
# --------------------------------------------------------------------------- #


async def test_save_binds_citations_to_the_given_message_id():
    """A regenerated answer is a new ChatMessage row, so it must get its own
    relation rather than inheriting the previous answer's."""
    repository = MagicMock()
    repository.ensure_citations = AsyncMock(return_value=[])
    repository.ensure_relations = AsyncMock(return_value=[])
    repository.find_by_message_id = AsyncMock(return_value=[])
    service = CitationRegistryService(repository)

    await service.save_citations(message_id=4242, items=[_rag_item("knowledgesearch_ab12cd34")], chat_id="chat-1")

    stored = repository.ensure_citations.await_args.args[0]
    relations = repository.ensure_relations.await_args.args[0]
    assert [row.message_id for row in stored] == [4242]
    assert [(r.message_id, r.citation_id) for r in relations] == [(4242, "knowledgesearch_ab12cd34")]

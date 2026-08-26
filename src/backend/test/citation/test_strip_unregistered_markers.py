"""A model that invents a citation id must not get a rendered footnote.

The prompt rules forbid fabricating an id, but nothing enforced them: on 116 a
workflow answered a video-file question with nothing but
``knowledgesearch_bixude.mp4:0`` — the file name substituted for the
id — and the client rendered a reference card whose detail endpoint then 404'd,
showing "溯源详情加载失败" as though the system had failed.
"""

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
    strip_unregistered_citation_markers,
)


def _item(citation_id: str) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=None,
            documentId=None,
            documentName="政策文件.pdf",
            items=[RagCitationItemSchema(itemId="0", chunkId="chunk-0", content="…")],
        ),
    )


def _marker(*keys: str) -> str:
    return CITATION_START_MARKER + CITATION_SEPARATOR_MARKER.join(keys) + CITATION_END_MARKER


def test_keeps_a_marker_whose_id_was_registered():
    text = f"答案。{_marker('knowledgesearch_5049a1e8:0')}"
    assert strip_unregistered_citation_markers(text, [_item("knowledgesearch_5049a1e8")]) == text


def test_drops_a_fabricated_id_the_registry_never_saw():
    # The 116 case: the answer was the marker and nothing else.
    text = _marker("knowledgesearch_bixude.mp4:0")
    assert strip_unregistered_citation_markers(text, []) == ""


def test_drops_only_the_fabricated_half_of_a_multi_source_marker():
    text = f"答案。{_marker('knowledgesearch_5049a1e8:0', 'knowledgesearch_made_up:1')}"
    result = strip_unregistered_citation_markers(text, [_item("knowledgesearch_5049a1e8")])
    assert result == f"答案。{_marker('knowledgesearch_5049a1e8:0')}"


def test_leaves_the_sentence_intact_when_the_whole_marker_goes():
    text = f"第一句。{_marker('knowledgesearch_made_up:0')}第二句。"
    assert strip_unregistered_citation_markers(text, []) == "第一句。第二句。"


def test_text_without_markers_is_returned_unchanged():
    text = "一段没有任何引用的普通回答。"
    assert strip_unregistered_citation_markers(text, []) is text


def test_a_key_missing_its_item_suffix_is_not_treated_as_registered():
    # `_split_citation_key` rejects a key with no ":", so it can never match a
    # registered id and must be dropped rather than passed through.
    text = _marker("knowledgesearch_5049a1e8")
    assert strip_unregistered_citation_markers(text, [_item("knowledgesearch_5049a1e8")]) == ""


def test_empty_and_none_text_are_safe():
    assert strip_unregistered_citation_markers("", []) == ""
    assert strip_unregistered_citation_markers(None, []) is None

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


def test_a_key_missing_its_item_suffix_is_remapped_onto_the_registered_key():
    # `_split_citation_key` rejects a key with no ":", so it cannot match as-is.
    # With a non-empty registry and no other registered marker, rewrite it.
    text = _marker("knowledgesearch_5049a1e8")
    assert strip_unregistered_citation_markers(text, [_item("knowledgesearch_5049a1e8")]) == _marker(
        "knowledgesearch_5049a1e8:0"
    )


def test_empty_and_none_text_are_safe():
    assert strip_unregistered_citation_markers("", []) == ""
    assert strip_unregistered_citation_markers(None, []) is None


def test_prompt_example_knowledgesearch_is_remapped_onto_temp_registry():
    """Models copy the citation-rules example id; remap it onto the real temp source."""
    from bisheng.citation.domain.schemas.citation_schema import (
        TempCitationItemSchema,
        TempCitationPayloadSchema,
    )

    temp = CitationRegistryItemSchema(
        citationId="tempsearch_2d7fbef5",
        type=CitationType.TEMP,
        itemId="0",
        sourcePayload=TempCitationPayloadSchema(
            documentId="399417360b744746b033d84954df0859",
            documentName="Filelib.pdf",
            items=[TempCitationItemSchema(itemId="0", content="chunk")],
        ),
    )
    text = "根据文档。" + _marker("knowledgesearch_18f5868b:0")
    assert strip_unregistered_citation_markers(text, [temp]) == "根据文档。" + _marker("tempsearch_2d7fbef5:0")


def test_prompt_example_is_not_remapped_when_a_real_marker_already_exists():
    from bisheng.citation.domain.schemas.citation_schema import (
        TempCitationItemSchema,
        TempCitationPayloadSchema,
    )

    temp = CitationRegistryItemSchema(
        citationId="tempsearch_2d7fbef5",
        type=CitationType.TEMP,
        itemId="0",
        sourcePayload=TempCitationPayloadSchema(
            documentId="399417360b744746b033d84954df0859",
            documentName="Filelib.pdf",
            items=[TempCitationItemSchema(itemId="0", content="chunk")],
        ),
    )
    text = "真来源。" + _marker("tempsearch_2d7fbef5:0") + "抄的示例。" + _marker("knowledgesearch_18f5868b:0")
    assert (
        strip_unregistered_citation_markers(text, [temp])
        == "真来源。" + _marker("tempsearch_2d7fbef5:0") + "抄的示例。"
    )


def test_only_the_first_unregistered_marker_is_remapped():
    text = "一段。" + _marker("knowledgesearch_18f5868b:0") + "二段。" + _marker("knowledgesearch_18f5868b:1")
    result = strip_unregistered_citation_markers(text, [_item("tempsearch_72dd97b6")])
    assert result == "一段。" + _marker("tempsearch_72dd97b6:0") + "二段。"


def _temp_item(citation_id: str, item_id: str, content: str) -> CitationRegistryItemSchema:
    from bisheng.citation.domain.schemas.citation_schema import (
        TempCitationItemSchema,
        TempCitationPayloadSchema,
    )

    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.TEMP,
        itemId=item_id,
        sourcePayload=TempCitationPayloadSchema(
            documentId="399417360b744746b033d84954df0859",
            documentName="Filelib.pdf",
            items=[TempCitationItemSchema(itemId=item_id, chunkIndex=int(item_id), content=content)],
        ),
    )


def test_copied_example_is_remapped_to_the_overlapping_chunk_not_the_first():
    """A trailing fake marker must land on the chunk that actually supports the answer."""
    items = [
        _temp_item("tempsearch_8ff0d680", "0", "1. 通用约定 Base URL"),
        _temp_item("tempsearch_8ff0d680", "17", "2. 查询知识资源列表"),
    ]
    text = "接口名称是查询知识资源列表。" + _marker("knowledgesearch_18f5868b:0")
    assert strip_unregistered_citation_markers(text, items) == "接口名称是查询知识资源列表。" + _marker(
        "tempsearch_8ff0d680:17"
    )


def test_numbered_list_gets_one_marker_per_matching_chunk():
    items = [
        _temp_item("tempsearch_8ff0d680", "0", "1. 通用约定"),
        _temp_item("tempsearch_8ff0d680", "17", "2. 查询知识资源列表"),
        _temp_item("tempsearch_8ff0d680", "39", "3. 查询文件列表"),
        _temp_item("tempsearch_8ff0d680", "57", "4. 查询文件详情"),
        _temp_item("tempsearch_8ff0d680", "80", "5. 检索知识库 Chunk"),
    ]
    text = (
        "列出的接口名称如下：\n"
        "1. 查询知识资源列表\n"
        "2. 查询文件列表\n"
        "3. 查询文件详情\n"
        "4. 检索知识库 Chunk\n" + _marker("knowledgesearch_18f5868b:0")
    )
    result = strip_unregistered_citation_markers(text, items)
    assert _marker("knowledgesearch_18f5868b:0") not in result
    assert "1. 查询知识资源列表" + _marker("tempsearch_8ff0d680:17") in result
    assert "2. 查询文件列表" + _marker("tempsearch_8ff0d680:39") in result
    assert "3. 查询文件详情" + _marker("tempsearch_8ff0d680:57") in result
    assert "4. 检索知识库 Chunk" + _marker("tempsearch_8ff0d680:80") in result

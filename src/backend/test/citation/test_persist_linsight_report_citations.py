"""F047: persist only citations actually referenced in a linsight report."""

from __future__ import annotations

import pytest

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services import citation_prompt_helper as helper
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_SEPARATOR_MARKER,
    CITATION_START_MARKER,
    persist_linsight_report_citations,
    serialize_citation_items_for_page,
    unescape_citation_markers,
)


def _marker(*keys: str) -> str:
    return CITATION_START_MARKER + CITATION_SEPARATOR_MARKER.join(keys) + CITATION_END_MARKER


def _rag_item(citation_id: str) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            documentId=11,
            documentName="政策.pdf",
            items=[RagCitationItemSchema(itemId="1", chunkId="c1", content="…", page=3)],
        ),
    )


def _web_item(citation_id: str) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.WEB,
        sourcePayload=WebCitationPayloadSchema(
            url="https://example.com/a",
            title="A",
            snippet="s",
            source="example.com",
        ),
    )


@pytest.fixture
def persist_mocks(monkeypatch: pytest.MonkeyPatch):
    saved: dict = {}

    async def fake_save(*, message_id, items, chat_id=None, flow_id=None):
        saved["message_id"] = message_id
        saved["items"] = items
        saved["chat_id"] = chat_id
        saved["flow_id"] = flow_id
        saved["calls"] = saved.get("calls", 0) + 1

    cache = {}

    async def fake_get(self, citation_ids):
        return [cache[cid] for cid in citation_ids if cid in cache]

    monkeypatch.setattr(helper, "save_message_citations", fake_save)
    monkeypatch.setattr(helper.CitationRuntimeCacheService, "get_citations_by_ids", fake_get)
    return saved, cache


async def test_persists_only_ids_present_in_report(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")
    cache["websearch_bbb"] = _web_item("websearch_bbb")
    cache["knowledgesearch_unused"] = _rag_item("knowledgesearch_unused")

    report = f"浓度下降。{_marker('knowledgesearch_aaa:1', 'websearch_bbb:0')}"
    items = await persist_linsight_report_citations(
        message_id=42,
        chat_id="chat-7",
        report_texts=["ignored unused", report],
    )

    assert saved["message_id"] == 42
    assert saved["chat_id"] == "chat-7"
    assert {item.citationId for item in saved["items"]} == {"knowledgesearch_aaa", "websearch_bbb"}
    assert {item.citationId for item in items} == {"knowledgesearch_aaa", "websearch_bbb"}


async def test_no_markers_does_not_save(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")

    items = await persist_linsight_report_citations(
        message_id=42,
        chat_id="chat-7",
        report_texts=["一篇没有任何引用的报告"],
    )

    assert saved == {}
    assert items == []


async def test_missing_message_id_does_not_save(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")

    items = await persist_linsight_report_citations(
        message_id=None,
        chat_id="chat-7",
        report_texts=[f"x{_marker('knowledgesearch_aaa:1')}"],
    )
    items_invalid_id = await persist_linsight_report_citations(
        message_id="not-int",
        chat_id="chat-7",
        report_texts=[f"x{_marker('knowledgesearch_aaa:1')}"],
    )

    assert saved == {}
    assert [item.citationId for item in items] == ["knowledgesearch_aaa"]
    assert [item.citationId for item in items_invalid_id] == ["knowledgesearch_aaa"]


async def test_cache_miss_skips_unknown_ids(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")

    items = await persist_linsight_report_citations(
        message_id=1,
        chat_id="c",
        report_texts=[f"x{_marker('knowledgesearch_aaa:1', 'knowledgesearch_ghost:0')}"],
    )

    assert [item.citationId for item in saved["items"]] == ["knowledgesearch_aaa"]
    assert [item.citationId for item in items] == ["knowledgesearch_aaa"]


async def test_repeat_call_still_saves_the_same_ids(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")
    text = f"结论。{_marker('knowledgesearch_aaa:1')}"

    first = await persist_linsight_report_citations(message_id=9, chat_id="c", report_texts=[text])
    second = await persist_linsight_report_citations(message_id=9, chat_id="c", report_texts=[text])

    assert saved["calls"] == 2
    assert [item.citationId for item in saved["items"]] == ["knowledgesearch_aaa"]
    assert [item.citationId for item in first] == ["knowledgesearch_aaa"]
    assert [item.citationId for item in second] == ["knowledgesearch_aaa"]


def test_unescape_citation_markers_turns_escapes_into_pua():
    escaped = "结论。\\ue200knowledgesearch_aaa:1\\ue202"
    doubled = "结论。\\\\ue200knowledgesearch_aaa:1\\\\ue202"
    real = f"结论。{_marker('knowledgesearch_aaa:1')}"
    assert unescape_citation_markers(escaped) == real
    assert unescape_citation_markers(doubled) == real
    assert unescape_citation_markers(real) == real
    assert unescape_citation_markers("plain") == "plain"


async def test_escaped_markers_in_report_still_persist(persist_mocks):
    saved, cache = persist_mocks
    cache["knowledgesearch_aaa"] = _rag_item("knowledgesearch_aaa")

    items = await persist_linsight_report_citations(
        message_id=42,
        chat_id="chat-7",
        report_texts=["结论。\\ue200knowledgesearch_aaa:1\\ue202"],
    )

    assert [item.citationId for item in saved["items"]] == ["knowledgesearch_aaa"]
    assert [item.citationId for item in items] == ["knowledgesearch_aaa"]


def test_serialize_citation_items_for_page_strips_rag_urls():
    item = CitationRegistryItemSchema(
        citationId="knowledgesearch_aaa",
        type=CitationType.RAG,
        accessScope="per_user",
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=9,
            knowledgeName="政策文档",
            documentId=11,
            documentName="政策.pdf",
            snippet="浓度下降",
            previewUrl="https://minio/preview",
            downloadUrl="https://minio/download",
            sourceUrl="https://minio/source",
            items=[RagCitationItemSchema(itemId="1", chunkId="c1", content="…", page=3)],
        ),
    )
    payloads = serialize_citation_items_for_page([item])
    assert payloads[0]["citationId"] == "knowledgesearch_aaa"
    assert payloads[0]["sourcePayload"]["documentName"] == "政策.pdf"
    assert payloads[0]["sourcePayload"]["knowledgeName"] == "政策文档"
    assert "previewUrl" not in payloads[0]["sourcePayload"]
    assert "downloadUrl" not in payloads[0]["sourcePayload"]
    assert "sourceUrl" not in payloads[0]["sourcePayload"]

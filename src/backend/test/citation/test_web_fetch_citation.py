"""A fetched web page is registered as one WEB citation source (F085)."""

import json
from types import SimpleNamespace

from bisheng.citation.domain.schemas.citation_schema import CitationType
from bisheng.citation.domain.services.citation_handle_service import (
    attach_web_url_markers,
    drop_web_citation_keys,
    item_identity,
    rewrite_web_results_with_handles,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    FETCHED_PAGE_ITEM_ID,
    FetchedPageCitationRegistry,
    annotate_fetched_page_with_citation,
    annotate_web_results_with_citations,
    collect_web_citation_registry_items,
    is_web_citation_tool,
)


def _page_output(url="https://example.com/a/", title="Example page", content=None) -> str:
    if content is None:
        content = (
            "# Example page\n\n![logo](https://example.com/logo.png)\n\n"
            "**First** paragraph of the [body](https://example.com/b).\n\nSecond."
        )
    return json.dumps(
        {
            "title": title,
            "url": url,
            "source": "example.com",
            "content": content,
            "truncated": False,
            "total_chars": len(content),
        },
        ensure_ascii=False,
    )


def test_is_web_citation_tool_matches_search_fetch_and_wrappers():
    assert is_web_citation_tool(SimpleNamespace(name="web_search"))
    assert is_web_citation_tool(SimpleNamespace(name="web_fetch"))
    assert is_web_citation_tool(SimpleNamespace(name="wrapped", tool_name="web_fetch"))
    assert not is_web_citation_tool(SimpleNamespace(name="search_knowledge_bases"))
    assert not is_web_citation_tool(None)


def test_fetched_page_becomes_one_web_source():
    output, items = annotate_fetched_page_with_citation(_page_output(), FetchedPageCitationRegistry())

    page = json.loads(output)
    assert len(items) == 1
    item = items[0]
    assert item.type == CitationType.WEB
    assert item.itemId == FETCHED_PAGE_ITEM_ID
    assert item.key == page["citation_key"]
    assert page["citation_key"].startswith("websearch_")
    payload = item.sourcePayload
    assert payload.url == "https://example.com/a"
    assert payload.title == "Example page"
    assert payload.source == "example.com"
    # The card snippet is plain text: no heading marks, no repeated title, no images.
    assert payload.snippet == "First paragraph of the body. Second."
    assert page["content"].startswith("# Example page")


def test_same_url_reuses_the_source_and_returns_items_again():
    registry = FetchedPageCitationRegistry()

    first_output, first_items = annotate_fetched_page_with_citation(_page_output("https://example.com/a/"), registry)
    second_output, second_items = annotate_fetched_page_with_citation(
        _page_output("https://EXAMPLE.com/a#section"), registry
    )

    assert json.loads(first_output)["citation_key"] == json.loads(second_output)["citation_key"]
    assert [item.key for item in second_items] == [item.key for item in first_items]


def test_different_urls_get_different_sources():
    registry = FetchedPageCitationRegistry()

    first_output, _ = annotate_fetched_page_with_citation(_page_output("https://example.com/a"), registry)
    second_output, _ = annotate_fetched_page_with_citation(_page_output("https://example.com/b"), registry)

    assert json.loads(first_output)["citation_key"] != json.loads(second_output)["citation_key"]


def test_text_output_is_not_annotated():
    registry = FetchedPageCitationRegistry()

    for output in ("网页读取失败：HTTP 404", "该网页没有可读正文。", json.dumps([{"url": "https://x.com"}])):
        assert annotate_fetched_page_with_citation(output, registry) == (output, [])


def test_fetch_and_search_of_the_same_url_stay_separate_sources():
    search_output = json.dumps(
        annotate_web_results_with_citations([{"title": "A", "url": "https://example.com/a", "snippet": "s"}])
    )
    search_items = collect_web_citation_registry_items(json.loads(search_output))
    _, fetch_items = annotate_fetched_page_with_citation(_page_output(), FetchedPageCitationRegistry())

    assert search_items[0].citationId != fetch_items[0].citationId
    # Short handles are allocated by identity; the two must not share one handle.
    assert item_identity(search_items[0]) != item_identity(fetch_items[0])


def test_url_searched_and_fetched_gets_one_marker_for_the_fetched_page():
    url = "https://example.com/report-source"
    entries = [
        {"type": "web", "key": "websearch_aaaa0001:1", "url": url, "urls": [url]},
        {"type": "web", "key": "websearch_bbbb0002:page", "url": url, "urls": [url]},
    ]

    marked = attach_web_url_markers(f"See {url} for details.", entries)

    assert marked.count("\ue200") == 1
    assert "websearch_bbbb0002:page" in marked


def test_handle_rewrite_accepts_a_single_page():
    output, items = annotate_fetched_page_with_citation(_page_output(), FetchedPageCitationRegistry())
    entries: list[dict] = []

    rewritten = json.loads(rewrite_web_results_with_handles(output, {items[0].key: "S4"}, entries))

    assert rewritten["ref"] == "S4"
    assert "citation_key" not in rewritten


def test_drop_keys_accepts_a_single_page():
    output, _ = annotate_fetched_page_with_citation(_page_output(), FetchedPageCitationRegistry())

    assert "citation_key" not in json.loads(drop_web_citation_keys(output))

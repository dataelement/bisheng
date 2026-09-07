"""Unit tests for markdown image annotate + ImageRegistry (F061 T001).

Covers AC: AC-01, AC-08
"""

from bisheng.common.image_view import ImageRegistry, annotate

_CHART = "/bucket/knowledge/images/1/2/chart.png"
_TABLE = "/bucket/knowledge/images/1/2/table.png"


def test_annotate_single_image_keeps_url_and_appends_anchor():
    registry = ImageRegistry()
    text = f"see ![chart]({_CHART}) here"

    out = annotate(text, registry)

    assert f"![chart]({_CHART})⟦img#1⟧" in out
    assert out.count(_CHART) == 1
    assert registry.get("img#1") == {"url": _CHART}
    assert len(registry) == 1


def test_annotate_two_urls_get_stable_sequential_ids():
    registry = ImageRegistry()
    text = f"![chart]({_CHART}) then ![table]({_TABLE})"

    out = annotate(text, registry)

    assert f"![chart]({_CHART})⟦img#1⟧" in out
    assert f"![table]({_TABLE})⟦img#2⟧" in out
    assert registry.get("img#1") == {"url": _CHART}
    assert registry.get("img#2") == {"url": _TABLE}
    assert len(registry) == 2


def test_annotate_same_url_twice_reuses_one_id():
    registry = ImageRegistry()
    text = f"![a]({_CHART}) and ![b]({_CHART})"

    out = annotate(text, registry)

    assert f"![a]({_CHART})⟦img#1⟧" in out
    assert f"![b]({_CHART})⟦img#1⟧" in out
    assert "⟦img#2⟧" not in out
    assert len(registry) == 1
    assert registry.get("img#1") == {"url": _CHART}


def test_annotate_without_markdown_image_is_noop():
    registry = ImageRegistry()
    text = "plain paragraph with <img src='/x.png'> html only"

    out = annotate(text, registry)

    assert out == text
    assert len(registry) == 0
    assert registry.get("img#1") is None


def test_annotate_does_not_rewrite_citation_private_use():
    registry = ImageRegistry()
    citation = "\ue200knowledgesearch_file:0\ue202"
    text = f"ref {citation} and ![c]({_CHART})"

    out = annotate(text, registry)

    assert citation in out
    assert f"![c]({_CHART})⟦img#1⟧" in out
    assert out.count("\ue200") == 1
    assert registry.get("img#1") == {"url": _CHART}

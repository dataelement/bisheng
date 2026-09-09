"""Unit tests for markdown image annotate + ImageRegistry (F061 T001).

Covers AC: AC-01, AC-08
"""

from bisheng.common.image_view.annotate import (
    ImageRegistry,
    annotate,
    missing_viewed_markdown,
    should_splice_viewed_images,
)

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


def test_missing_viewed_markdown_appends_only_viewed_urls():
    registry = ImageRegistry()
    annotate(f"![chart]({_CHART}) ![table]({_TABLE})", registry)
    registry.record_viewed("img#2", "data:image/png;base64,aaa")
    registry.pop_viewed()

    extra = missing_viewed_markdown("我将显示 img#2。", registry)

    assert _TABLE in extra
    assert _CHART not in extra
    assert extra.startswith("\n\n")
    assert f"![{_TABLE.rsplit('/', 1)[-1]}]({_TABLE})" in extra


def test_missing_viewed_markdown_skips_when_url_already_present():
    registry = ImageRegistry()
    annotate(f"![chart]({_CHART})", registry)
    registry.record_viewed("img#1", "data:image/png;base64,aaa")

    extra = missing_viewed_markdown(f"see ![]({_CHART})", registry)

    assert extra == ""


def test_missing_viewed_markdown_empty_when_nothing_viewed():
    registry = ImageRegistry()
    annotate(f"![chart]({_CHART})", registry)

    assert missing_viewed_markdown("我将显示 img#1。", registry) == ""


def test_missing_viewed_markdown_skips_when_answer_does_not_claim_display():
    registry = ImageRegistry()
    annotate(f"![chart]({_CHART})", registry)
    registry.record_viewed("img#1", "data:image/png;base64,aaa")

    extra = missing_viewed_markdown("单据编号、单位名称、账户类型。", registry)

    assert extra == ""


def test_should_splice_viewed_images_follows_model_answer():
    assert should_splice_viewed_images("我将显示 img#7。")
    assert should_splice_viewed_images("如下图所示。")
    assert not should_splice_viewed_images("单据编号、单位名称。")
    assert not should_splice_viewed_images("开户登记相关截图。")

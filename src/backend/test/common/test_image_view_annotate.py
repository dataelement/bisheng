"""Unit tests for markdown image annotate + ImageRegistry (F061 T001).

Covers AC: AC-01, AC-08
"""

from bisheng.common.image_view.annotate import (
    ImageIdLineConverter,
    ImageRegistry,
    annotate,
    question_wants_pictures,
    render_image_id_lines,
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


def _two_images() -> ImageRegistry:
    registry = ImageRegistry()
    annotate(f"![chart]({_CHART}) ![table]({_TABLE})", registry)
    return registry


def test_id_only_line_renders_that_picture():
    out = render_image_id_lines("这是第一张图片：\nimg#2\n说明结束。", _two_images())

    assert out == f"这是第一张图片：\n![table.png]({_TABLE})\n说明结束。"


def test_bracketed_id_lines_render_each_named_picture():
    out = render_image_id_lines("图片如下：\n⟦img#1⟧\n[img#2]", _two_images())

    assert f"![chart.png]({_CHART})" in out
    assert f"![table.png]({_TABLE})" in out


def test_id_inside_a_sentence_is_a_mention_not_a_picture():
    text = "img#1 是走势图，img#2 不符合问题。"

    assert render_image_id_lines(text, _two_images()) == text


def test_claim_without_a_picture_line_is_not_filled_in():
    registry = _two_images()
    registry.record_viewed("img#1", "data:image/png;base64,aaa")
    registry.record_viewed("img#2", "data:image/png;base64,bbb")
    text = "根据您的请求，这里是相关的图片展示："

    assert render_image_id_lines(text, registry) == text


def test_unknown_id_line_is_left_alone():
    assert render_image_id_lines("img#9", _two_images()) == "img#9"


def test_stream_conversion_matches_whole_text_however_it_is_chunked():
    text = "前言 img#1 提到。\n这是第一张图片：\nimg#1\n\n  img#2  \n结尾"
    expected = render_image_id_lines(text, _two_images())
    for size in (1, 2, 3, 5, 8):
        converter = ImageIdLineConverter(_two_images())
        parts = [text[i : i + size] for i in range(0, len(text), size)]
        out = "".join(converter.feed(part) for part in parts) + converter.flush()
        assert out == expected
        assert converter.rendered_ids == ["img#1", "img#2"]


def test_plain_text_is_not_held_back():
    converter = ImageIdLineConverter(_two_images())

    assert converter.feed("走势向上") == "走势向上"
    assert converter.feed("img") == "img"


def test_converter_feeds_its_output_to_the_inner_converter():
    class _Upper:
        stats = "inner-stats"

        def feed(self, text: str) -> str:
            return text.upper()

        def flush(self) -> str:
            return "!"

    converter = ImageIdLineConverter(_two_images(), _Upper())

    assert converter.feed("ok\nimg#1") == "OK\n"
    assert converter.flush() == f"![CHART.PNG]({_CHART.upper()})!"
    assert converter.stats == "inner-stats"


def test_question_wants_pictures_only_gates_citation_stripping():
    assert question_wants_pictures("这张图的走势") is False
    assert question_wants_pictures("找出文档中美女的图片") is True

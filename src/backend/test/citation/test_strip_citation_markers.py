# ruff: noqa: RUF001 - the assertions are about full-width CJK punctuation surviving
"""Export outputs must lose the whole citation span, ids included.

The preview parses ``\ue200knowledgesearch_18f5868b:0\ue202`` into a badge, but
Word / PDF / a downloaded ``.md`` render the wrapper chars as nothing and the id
as plain text, so the raw ``knowledgesearch_18f5868b:0`` leaked into every
deliverable. ``strip_citation_markers`` is the one helper the export paths share.
"""

from __future__ import annotations

from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_SEPARATOR_MARKER,
    CITATION_START_MARKER,
    strip_citation_markers,
)

_PUA = (CITATION_START_MARKER, CITATION_SEPARATOR_MARKER, CITATION_END_MARKER)


def _marker(*keys: str) -> str:
    return CITATION_START_MARKER + CITATION_SEPARATOR_MARKER.join(keys) + CITATION_END_MARKER


def _has_pua(text: str) -> bool:
    return any(ch in text for ch in _PUA)


def test_single_span_is_removed_with_its_id():
    text = f"PM2.5 年均浓度下降。{_marker('knowledgesearch_18f5868b:0')} 下一句。"
    result = strip_citation_markers(text)
    assert result == "PM2.5 年均浓度下降。 下一句。"
    assert "knowledgesearch_" not in result
    assert not _has_pua(result)


def test_multi_source_span_with_separator_is_removed_whole():
    text = f"结论。{_marker('knowledgesearch_18f5868b:0', 'websearch_3a1c9f22:0')}"
    result = strip_citation_markers(text)
    assert result == "结论。"
    assert "websearch_" not in result
    assert not _has_pua(result)


def test_escaped_literal_form_is_removed_too():
    escaped = "结论。\\ue200knowledgesearch_18f5868b:0\\ue202 后文"
    doubled = "结论。\\\\ue200knowledgesearch_18f5868b:0\\\\ue202 后文"
    assert strip_citation_markers(escaped) == "结论。 后文"
    assert strip_citation_markers(doubled) == "结论。 后文"


def test_unterminated_start_marker_drops_marker_and_id_only():
    text = f"第一句{CITATION_START_MARKER}knowledgesearch_18f5868b:0。第二句\n第三句"
    result = strip_citation_markers(text)
    assert result == "第一句。第二句\n第三句"
    assert not _has_pua(result)


def test_unterminated_marker_does_not_swallow_prose_before_a_later_span():
    text = f"第一段{CITATION_START_MARKER}knowledgesearch_aaa:1\n\n第二段保留。{_marker('websearch_bbb:0')}\n"
    result = strip_citation_markers(text)
    assert result == "第一段\n\n第二段保留。\n"
    assert "knowledgesearch_" not in result and "websearch_" not in result
    assert not _has_pua(result)


def test_stray_separator_and_end_markers_are_dropped():
    text = f"a{CITATION_SEPARATOR_MARKER}b{CITATION_END_MARKER}c"
    assert strip_citation_markers(text) == "abc"


def test_text_without_markers_is_returned_unchanged():
    plain = "没有任何引用的一段话。  两个空格\n\n保留空行\tTab"
    assert strip_citation_markers(plain) == plain
    assert strip_citation_markers("") == ""


def test_cjk_punctuation_and_surrounding_whitespace_are_preserved():
    text = (
        f"「引号」，{_marker('knowledgesearch_18f5868b:0')}；括号（内容）。\n"
        f"  缩进保留 {_marker('websearch_3a1c9f22:1')}\n"
    )
    result = strip_citation_markers(text)
    assert result == "「引号」，；括号（内容）。\n  缩进保留 \n"


def test_markdown_structure_survives():
    md = (
        "# 标题\n\n"
        f"- 要点一{_marker('knowledgesearch_aaa:1')}\n"
        f"- 要点二{_marker('knowledgesearch_aaa:2', 'websearch_bbb:0')}\n\n"
        "| 列 | 值 |\n|---|---|\n"
        f"| a | 1{_marker('knowledgesearch_aaa:3')} |\n"
    )
    result = strip_citation_markers(md)
    assert result == "# 标题\n\n- 要点一\n- 要点二\n\n| 列 | 值 |\n|---|---|\n| a | 1 |\n"


def test_unterminated_marker_keeps_unrelated_colon_token():
    """A dangling start marker must not take a clock time or ratio with it."""
    text = "A \ue200 10:30 meeting"
    assert strip_citation_markers(text) == "A  10:30 meeting"


def test_unterminated_marker_drops_registry_shaped_id():
    text = "答。\ue200knowledgesearch_18f5868b:0 后文"
    assert strip_citation_markers(text) == "答。 后文"

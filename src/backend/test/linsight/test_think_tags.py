"""Unit tests for the reasoning-model ``<think>`` marker strippers.

Covers both semantics:
- ``strip_think_block`` — discard the whole ``<think>...</think>`` region (answers/titles)
- ``strip_reasoning_tags`` — drop only the markers, keep the inner reasoning (narration)
"""

from __future__ import annotations

from bisheng.common.utils.think_tags import strip_reasoning_tags, strip_think_block


class TestStripThinkBlock:
    def test_removes_full_block_keeps_outside(self):
        assert strip_think_block("<think>推理过程</think>调研报告") == "调研报告"

    def test_pure_block_becomes_empty(self):
        assert strip_think_block("<think>只有推理没有正文</think>") == ""

    def test_multiple_blocks_all_removed_non_greedy(self):
        # Greedy `.*` would eat "保留" between the two blocks; non-greedy keeps it.
        assert strip_think_block("<think>a</think>保留<think>b</think>尾") == "保留尾"

    def test_stray_unpaired_open_marker_dropped(self):
        assert strip_think_block("<think>标题被截断") == "标题被截断"

    def test_leading_trailing_whitespace_stripped(self):
        assert strip_think_block("  <think>x</think>  报告 ") == "报告"

    def test_case_insensitive(self):
        assert strip_think_block("<THINK>x</THINK>报告") == "报告"

    def test_no_tag_returns_stripped_text(self):
        assert strip_think_block("  干净标题  ") == "干净标题"

    def test_empty_and_none_safe(self):
        assert strip_think_block("") == ""
        assert strip_think_block(None) is None  # type: ignore[arg-type]


class TestStripReasoningTags:
    def test_keeps_inner_text_drops_markers(self):
        assert strip_reasoning_tags("<think>\n分析问题\n</think>") == "\n分析问题\n"

    def test_marker_only_reduces_to_empty_after_strip(self):
        assert strip_reasoning_tags("<think>").strip() == ""

    def test_stream_truncated_open_marker(self):
        # A half tag "<think" (closing ">" split off across chunks) is still dropped.
        assert strip_reasoning_tags("<think").strip() == ""

    def test_stream_truncated_close_marker(self):
        assert strip_reasoning_tags("</think").strip() == ""

    def test_trailing_close_marker_on_reasoning_delta(self):
        assert strip_reasoning_tags("得出结论</think>") == "得出结论"

    def test_does_not_delete_reasoning_between_markers(self):
        # Unlike strip_think_block, the inner reasoning is preserved here.
        assert "关键分析" in strip_reasoning_tags("<think>关键分析</think>")

    def test_no_tag_untouched(self):
        text = "先分析用户意图后给出结论"
        assert strip_reasoning_tags(text) == text

    def test_empty_and_none_safe(self):
        assert strip_reasoning_tags("") == ""
        assert strip_reasoning_tags(None) is None  # type: ignore[arg-type]

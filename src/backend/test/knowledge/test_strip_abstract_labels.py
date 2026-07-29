"""Unit tests for abstract label stripping used by ingest and backfill."""

from __future__ import annotations

from bisheng.knowledge.rag.pipeline.transformer.abstract import (
    clean_document_abstract,
    strip_abstract_labels,
)


def test_strip_abstract_labels_removes_summary_prefix_with_fullwidth_colon():
    assert strip_abstract_labels("【摘要】：本文档汇总了市场动向。") == "本文档汇总了市场动向。"


def test_strip_abstract_labels_removes_summary_prefix_with_halfwidth_colon():
    assert strip_abstract_labels("【摘要】: hello") == "hello"


def test_strip_abstract_labels_removes_bare_summary_prefix():
    assert strip_abstract_labels("【摘要】本文档汇总了市场动向。") == "本文档汇总了市场动向。"


def test_strip_abstract_labels_removes_document_type_line():
    raw = "【文档类型】：市场快讯\n【摘要】：本文档汇总了市场动向。"
    assert strip_abstract_labels(raw) == "本文档汇总了市场动向。"


def test_strip_abstract_labels_noop_for_clean_text():
    text = "本文档汇总了2025年2月12日宏观经济政策动向。"
    assert strip_abstract_labels(text) == text


def test_strip_abstract_labels_handles_empty():
    assert strip_abstract_labels("") == ""
    assert strip_abstract_labels(None) is None  # type: ignore[arg-type]


def test_clean_document_abstract_strips_think_and_labels():
    raw = "<think>scratch</think>\n【文档类型】：会议纪要\n【摘要】：最终决定加强推广。"
    assert clean_document_abstract(raw) == "最终决定加强推广。"

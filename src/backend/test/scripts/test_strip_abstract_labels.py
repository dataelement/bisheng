"""Unit tests for the strip_abstract_labels backfill script helpers."""

from __future__ import annotations

import scripts.strip_abstract_labels as script


def test_abstract_needs_strip_detects_summary_marker():
    assert script.abstract_needs_strip("【摘要】：正文") is True
    assert script.abstract_needs_strip("正文【摘要】残留") is True


def test_abstract_needs_strip_detects_document_type_marker():
    assert script.abstract_needs_strip("【文档类型】：报告\n正文") is True


def test_abstract_needs_strip_false_for_clean_or_empty():
    assert script.abstract_needs_strip("干净摘要正文") is False
    assert script.abstract_needs_strip("") is False
    assert script.abstract_needs_strip(None) is False


def test_script_uses_shared_strip_helper():
    """Backfill must reuse the same strip function as AbstractTransformer."""
    from bisheng.knowledge.rag.pipeline.transformer.abstract import strip_abstract_labels

    assert script.strip_abstract_labels is strip_abstract_labels
    assert script.strip_abstract_labels("【摘要】：x") == "x"

"""F118 preserves the existing splitter's character-fallback separator.

Coverage: AC-39, AC-42, AC-43, AC-44. An empty separator element is an
existing parsing rule; an empty separator list and mismatched rules are not
valid normalized settings.
"""

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.processing_settings import DocumentProcessingRule, PartialDocumentRule
from bisheng_langchain.text_splitter import _split_text_with_regex


@pytest.fixture
def document_rule_values():
    return {
        "split_mode": "custom",
        "separator": ["\n"],
        "separator_rule": ["after"],
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "hierarchy_level": 3,
        "append_title": False,
        "max_chunk_size": 1000,
        "retain_images": 1,
        "force_ocr": 1,
        "enable_formula": 1,
        "filter_page_header_footer": 0,
    }


@pytest.mark.parametrize("separators", [["\n", ""], [""]])
def test_complete_rule_keeps_existing_character_fallback(document_rule_values, separators):
    rule = DocumentProcessingRule(
        **{
            **document_rule_values,
            "separator": separators,
            "separator_rule": ["after"] * len(separators),
        }
    )
    assert rule.model_dump()["separator"] == separators
    assert _split_text_with_regex("甲乙", rule.separator[-1], True, rule.separator_rule[-1]) == ["甲", "乙"]


@pytest.mark.parametrize("separators", [["\n", ""], [""]])
def test_partial_override_keeps_explicit_character_fallback(separators):
    rule = PartialDocumentRule(separator=separators, separator_rule=["after"] * len(separators))
    assert rule.model_dump(exclude_none=True) == {
        "separator": separators,
        "separator_rule": ["after"] * len(separators),
    }


@pytest.mark.parametrize("model", [DocumentProcessingRule, PartialDocumentRule])
def test_normalized_separator_list_must_not_be_empty(document_rule_values, model):
    values = document_rule_values if model is DocumentProcessingRule else {}
    with pytest.raises(ValidationError):
        model.model_validate({**values, "separator": [], "separator_rule": []})


@pytest.mark.parametrize("model", [DocumentProcessingRule, PartialDocumentRule])
def test_separator_rule_count_still_matches_character_fallback(document_rule_values, model):
    values = document_rule_values if model is DocumentProcessingRule else {}
    with pytest.raises(ValidationError, match="same length"):
        model.model_validate({**values, "separator": ["\n", ""], "separator_rule": ["after"]})

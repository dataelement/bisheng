"""Unit tests for ask_user clarify-option normalization (is_default support).

The backend now emits each option as {"text", "is_default"} (back-compatible with
a bare string) so the frontend ClarifyCard can pre-select the default + ★-badge it.
is_default only drives the card; the answer value is the option text.
"""

from bisheng.linsight.domain.services.agent_factory import _norm_option


def test_norm_option_plain_string():
    assert _norm_option("选项A") == {"text": "选项A", "is_default": False}


def test_norm_option_dict_with_is_default():
    assert _norm_option({"text": "markdown", "is_default": True}) == {"text": "markdown", "is_default": True}


def test_norm_option_dict_without_is_default():
    assert _norm_option({"text": "html"}) == {"text": "html", "is_default": False}


def test_norm_option_value_label_fallback():
    """demo-style {value,label} keys still resolve a text (back-compat)."""
    assert _norm_option({"label": "Word", "is_default": True})["text"] == "Word"
    assert _norm_option({"value": "docx"})["text"] == "docx"
    assert _norm_option({"value": "docx"})["is_default"] is False

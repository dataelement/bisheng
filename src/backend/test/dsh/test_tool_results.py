"""AC-18, AC-19, AC-21, AC-23, AC-24, AC-25, AC-28: result contracts."""

import json

import pytest

from bisheng.common.errcode.dsh import DshToolOutputTooLargeError, DshToolResultInvalidError
from bisheng.dsh.domain.services.tool_results import normalize_result, strict_json


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"value":1}', {"value": 1}),
        ("[1,2]", [1, 2]),
        ("null", None),
        ("true", True),
        ("3", 3),
        ('"text"', "text"),
        ("hello", {"text": "hello"}),
        ("", {"text": ""}),
    ],
)
def test_generic_normalization(raw, expected):
    """AC-18: parse once and retain ordinary text with a stable representation."""
    assert normalize_result("weather", raw, 1024) == expected


@pytest.mark.parametrize("value", ['{"x":1,"x":2}', "[NaN]", '{"x":Infinity}'])
def test_strict_json_rejects_ambiguity(value):
    with pytest.raises(ValueError):
        strict_json(value)


def test_search_empty_and_truncated():
    """AC-23, AC-25: validate all rows before truncating, preserving source truncation."""
    assert normalize_result("bs_web_search", '{"results":[],"truncated":false}', 1024) == {
        "results": [],
        "truncated": False,
    }
    raw = {"results": [{"url": f"https://example.com/{i}"} for i in range(25)], "truncated": False}
    result = normalize_result("bs_web_search", json.dumps(raw), 10000)
    assert len(result["results"]) == 20 and result["truncated"] is True
    raw["results"][-1]["url"] = "javascript:invalid"
    with pytest.raises(DshToolResultInvalidError):
        normalize_result("bs_web_search", json.dumps(raw), 10000)


@pytest.mark.parametrize(
    "raw",
    [
        "hello",
        '{"encrypted_output":"opaque"}',
        '{"error":"failed"}',
        '{"results":[],"truncated":0}',
        '{"results":[{"url":"file:///x"}],"truncated":false}',
        '{"results":[],"truncated":false,"error":"failed"}',
        '{"results":[],"truncated":false,"output":null}',
    ],
)
def test_search_invalid_is_not_success(raw):
    """AC-24: failures, text and opaque encrypted output never become search results."""
    with pytest.raises(DshToolResultInvalidError):
        normalize_result("bs_web_search", raw, 10000)


def test_output_size_applies_to_serialized_value():
    """AC-28: text wrapper expansion is included in the output cap."""
    with pytest.raises(DshToolOutputTooLargeError):
        normalize_result("weather", "hello", 5)

"""Provider/model output is bounded structured data, never executable Python."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng_langchain.gpts.tools.web_search import tool as search
from bisheng_langchain.utils.structured_output import (
    MAX_OUTPUT_BYTES,
    StructuredOutputError,
    parse_data,
    parse_score,
)


def _bing(monkeypatch, response):
    monkeypatch.setattr(search, "BingSearchAPIWrapper", lambda **kwargs: object())
    monkeypatch.setattr(search, "BingSearchResults", lambda **kwargs: SimpleNamespace(invoke=lambda _: response))
    return search.BingSearch(api_key="test")._invoke("query")


@pytest.mark.parametrize("encoding", [str, json.dumps, lambda value: value])
def test_bing_preserves_repr_json_and_structured_results(monkeypatch, encoding):
    rows = [{"title": "引号 ' and \\", "link": "https://example.com/page", "snippet": "result", "thumbnail": None}]
    result = _bing(monkeypatch, encoding(rows))
    assert result[0]["title"] == rows[0]["title"]
    assert result[0]["snippet"] == "result"
    assert result[0]["url"] == "https://example.com/page"
    assert result[0]["source"] == "example.com"


def test_bing_never_calls_marker_from_provider_output(monkeypatch):
    marker = Mock(return_value="harmless")
    monkeypatch.setattr(search, "marker", marker, raising=False)
    with pytest.raises(StructuredOutputError):
        _bing(monkeypatch, "[{'snippet': marker(), 'link': 'https://example.com'}]")
    marker.assert_not_called()


@pytest.mark.parametrize(
    "bad", ["{'title':'not a list'}", "[None]", "[1]", "[{'link':123}]", "[{'title':[]}]", [{"id": True}], [{}] * 101]
)
def test_bing_rejects_wrong_protocol_types(monkeypatch, bad):
    with pytest.raises(StructuredOutputError):
        _bing(monkeypatch, bad)


@pytest.mark.parametrize(
    "bad",
    [
        "marker()",
        "[x for x in []]",
        "[].__class__",
        "[1] * 1000000",
        "{'a':1,'a':2}",
        '{"a":1,"a":2}',
        "{1: 'not a text key'}",
        "{1,2}",
        "(1,2)",
        "b'bytes'",
        "...",
        "NaN",
        "[1e999]",
        "[" * 50 + "0" + "]" * 50,
        "[" + ",".join("0" for _ in range(10001)) + "]",
        "x" * (MAX_OUTPUT_BYTES + 1),
    ],
)
def test_data_parser_rejects_expressions_invalid_types_and_resource_exhaustion(bad):
    with pytest.raises(StructuredOutputError):
        parse_data(bad, python_literals=True)


def test_structured_values_have_same_bounds_as_text():
    value = []
    value.append(value)
    with pytest.raises(StructuredOutputError):
        parse_data(value)
    with pytest.raises(StructuredOutputError):
        parse_data({"x": object()})


@pytest.mark.parametrize("text, expected", [("0", 0.0), ("10", 10.0), ("7.5", 7.5), (" .5\n", 0.5), ("7.", 7.0)])
def test_qa_score_decimal_contract(text, expected):
    assert parse_score(text) == expected


@pytest.mark.parametrize(
    "text", ["...", "1..", "marker()", "1+2", "1e3", "NaN", "Infinity", "11", "-1", "\uff19", "9" * 33, None, True, 7]
)
def test_qa_score_rejects_code_malformed_and_out_of_range_values(text):
    with pytest.raises(StructuredOutputError):
        parse_score(text)


def test_qa_consumer_uses_score_and_validates_verdict_output():
    from bisheng_langchain.chains.qa_generation.base_v2 import load_as_json, load_as_score

    assert load_as_score("7.5") == 7.5
    assert load_as_json('```json\n{"reason":"clear", "verdict":"Yes"}\n```') == {"reason": "clear", "verdict": "Yes"}
    for invalid in [
        "{}",
        "[]",
        '{"verdict":true,"reason":"x"}',
        '{"verdict":"Yes","reason":7}',
        '{"verdict":"Yes","reason":"x","extra":0}',
    ]:
        with pytest.raises(StructuredOutputError):
            load_as_json(invalid)
    with pytest.raises(StructuredOutputError):
        load_as_score("...")


def test_registered_bing_search_preserves_code_looking_snippet_as_data(monkeypatch):
    from bisheng_langchain.gpts.load_tools import load_tools

    marker = Mock()
    monkeypatch.setattr(search, "marker", marker, raising=False)
    rows = [{"snippet": "marker()", "title": "result", "link": "https://example.com"}]
    monkeypatch.setattr(search.BingSearchAPIWrapper, "results", lambda self, query, num_results: rows)
    tool = load_tools(
        {"web_search": {"type": "bing", "config": {"bing": {"api_key": "test", "base_url": "https://example.com"}}}}
    )[0]
    result = json.loads(tool.invoke({"query": "question"}))
    assert result[0]["snippet"] == "marker()"
    marker.assert_not_called()


def test_invalid_qa_verdict_fails_instead_of_accepting_question():
    from bisheng_langchain.chains.qa_generation.base_v2 import TrainsetGenerator

    def llm(messages):
        return SimpleNamespace(content="{}")

    generator = TrainsetGenerator(llm, llm)
    with pytest.raises(StructuredOutputError):
        generator._filter_question("Question")


@pytest.mark.parametrize("value", ['"\\ud800"', "\ud800", {"text": "\ud800"}])
def test_invalid_unicode_is_redacted(value):
    with pytest.raises(StructuredOutputError) as error:
        parse_data(value)
    assert "\\ud800" not in str(error.value)

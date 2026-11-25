"""Bing's real repr wire format must be parsed as data, not code."""

from unittest.mock import Mock

import pytest

from bisheng_langchain.gpts.tools.web_search import tool
from bisheng_langchain.utils.structured_output import StructuredOutputError

pytestmark = pytest.mark.mock


def _search(monkeypatch, response):
    monkeypatch.setattr(tool, "BingSearchAPIWrapper", Mock())
    monkeypatch.setattr(tool, "BingSearchResults", Mock(return_value=Mock(invoke=Mock(return_value=response))))
    return tool.BingSearch(api_key="synthetic-test-key", base_url="https://example.invalid/search")


def test_bing_real_repr_snippet_remains_data(monkeypatch, tmp_path):
    marker = tmp_path / "must-not-exist"
    snippet = f"__import__('pathlib').Path({str(marker)!r}).touch()\nquotes: ' and \""
    search = _search(monkeypatch, repr([{"title": "Result", "link": "https://example.invalid/a", "snippet": snippet}]))
    result = search._invoke("query")
    assert result[0]["snippet"] == snippet
    assert result[0]["url"] == "https://example.invalid/a"
    assert not marker.exists()


@pytest.mark.parametrize("response", ["__import__('os').getcwd()", "{}", "[{'snippet': 42}]", repr([{}] * 101)])
def test_bing_rejects_non_data_or_invalid_shape(monkeypatch, response):
    with pytest.raises(StructuredOutputError):
        _search(monkeypatch, response)._invoke("query")

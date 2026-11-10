"""Verify the Firecrawl HTTP adapter without network calls or middleware."""

import ast
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, Field


@pytest.fixture
def adapter():
    # Keep the real adapter, avoiding unrelated LangChain package initialization.
    path = Path(__file__).parents[2] / "bisheng_langchain/gpts/tools/api_tools/firecrawl.py"
    tree = ast.parse(path.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    http = SimpleNamespace(post=Mock(), get=Mock())
    namespace = {"BaseModel": BaseModel, "Field": Field, "Any": Any, "requests": http, "time": time}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["FireCrawl"], http


def response(payload, text="result", status=200):
    return SimpleNamespace(status_code=status, text=text, json=lambda: payload)


@pytest.mark.parametrize("depth", [0, 1, 2, 5])
def test_crawl_uses_v2_and_preserves_path_depth(adapter, depth, monkeypatch):
    cls, http = adapter
    status_url = "https://api.firecrawl.dev/v2/crawl/job-id"
    http.post.return_value = response({"url": status_url})
    http.get.side_effect = [response({"status": "scraping"}), response({"status": "completed"}, "markdown results")]
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    tool = cls(api_key="test-key", base_url="https://api.firecrawl.dev", maxdepth=depth, limit=10, timeout=30)

    assert tool.search_crawl("https://example.com") == "markdown results"

    assert http.post.call_args.args == ("https://api.firecrawl.dev/v2/crawl",)
    payload = http.post.call_args.kwargs["json"]
    assert payload["url"] == "https://example.com"
    assert payload["limit"] == 10
    assert payload["scrapeOptions"] == {"formats": ["markdown"]}
    assert "maxDepth" not in payload
    assert payload["regexOnFullURL"] is False
    patterns = payload["includePaths"]
    for count in range(depth + 1):
        path = "/" + "/".join(["page"] * count)
        assert any(re.fullmatch(pattern, path) for pattern in patterns)
        for suffix in ("/index.html", "/index.php"):
            assert any(re.fullmatch(pattern, path.rstrip("/") + suffix) for pattern in patterns)
    assert not any(re.fullmatch(pattern, "/" + "/".join(["page"] * (depth + 1))) for pattern in patterns)
    assert http.get.call_count == 2
    assert all(call.args == (status_url,) for call in http.get.call_args_list)
    sleep.assert_called_once_with(5)


def test_scrape_uses_v2_and_keeps_response_contract(adapter):
    cls, http = adapter
    http.post.return_value = response({}, '{"success":true,"data":{"markdown":"hello"}}')
    tool = cls(api_key="test-key", base_url="https://api.firecrawl.dev", maxdepth=1, limit=10, timeout=30000)

    assert tool.search_scrape("https://example.com") == http.post.return_value.text
    assert http.post.call_args.args == ("https://api.firecrawl.dev/v2/scrape",)
    assert http.post.call_args.kwargs["json"] == {
        "url": "https://example.com",
        "formats": ["markdown"],
        "timeout": 30000,
    }
    assert http.post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_crawl_reports_provider_failure(adapter):
    cls, http = adapter
    http.post.return_value = response({}, "rate limited", status=429)
    tool = cls(api_key="test-key", base_url="https://api.firecrawl.dev", maxdepth=1, limit=10, timeout=30)

    assert tool.search_crawl("https://example.com") == "failed with status code: 429, rate limited"
    http.get.assert_not_called()

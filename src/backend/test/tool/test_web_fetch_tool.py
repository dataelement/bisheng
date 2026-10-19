"""The web fetch built-in tool: engine request, post-processing and failure text.

Every failure is returned to the model as text so the conversation or task keeps
running (F085 design decision 7).
"""

import json
from unittest.mock import MagicMock, patch

import requests

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.tools.web_fetch import tool as web_fetch_tool
from bisheng_langchain.gpts.tools.web_fetch.tool import (
    DEFAULT_MAX_CHARS,
    DeepSeekFetch,
    WebFetchTool,
    unescape_markdown,
)

DEEPSEEK_URL = "https://api.deepseek.com/v1/tools/fetch"


def _response(status_code: int, payload: dict):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload
    response.text = json.dumps(payload)
    return response


def _build(extra: dict | None = None) -> WebFetchTool:
    if extra is None:
        extra = {"type": "deepseek", "config": {"deepseek": {"api_key": "sk-test", "base_url": ""}}}
    return load_tools({"web_fetch": extra})[0]


def _fetch(tool: WebFetchTool, url: str, payload: dict, status_code: int = 200):
    with patch.object(web_fetch_tool.requests, "post", return_value=_response(status_code, payload)) as call:
        output = tool.invoke({"url": url})
    return output, call


def test_load_tools_builds_web_fetch_tool():
    tool = _build()

    assert isinstance(tool, WebFetchTool)
    assert tool.name == "web_fetch"
    assert isinstance(tool.api_wrapper, DeepSeekFetch)
    assert tool.max_chars == DEFAULT_MAX_CHARS


def test_request_uses_default_endpoint_bearer_key_and_timeout():
    output, call = _fetch(_build(), "https://example.com/a", {"title": "A", "content": "Body"})

    assert call.call_args.args[0] == DEEPSEEK_URL
    assert call.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert call.call_args.kwargs["json"] == {"url": "https://example.com/a"}
    assert call.call_args.kwargs["timeout"] == (10, 60)
    page = json.loads(output)
    assert page == {
        "title": "A",
        "url": "https://example.com/a",
        "source": "example.com",
        "content": "Body",
        "truncated": False,
        "total_chars": 4,
    }


def test_base_url_override():
    tool = _build(
        {"type": "deepseek", "config": {"deepseek": {"api_key": "k", "base_url": "https://proxy.example.com/f"}}}
    )

    _, call = _fetch(tool, "https://example.com/a", {"title": "A", "content": "Body"})

    assert call.call_args.args[0] == "https://proxy.example.com/f"


def test_engine_escapes_are_removed_outside_code_blocks():
    content = "\\# Title\n\nA\\-B\\: c\\, d\\.\n\n```\npath\\-keep \\#\n```\n\nend\\!"

    assert unescape_markdown(content) == "# Title\n\nA-B: c, d.\n\n```\npath\\-keep \\#\n```\n\nend!"


def test_escaped_letters_and_cjk_are_kept():
    assert unescape_markdown("C:\\new \\中") == "C:\\new \\中"


def test_content_over_limit_is_truncated_with_note():
    tool = _build({"type": "deepseek", "config": {"deepseek": {"api_key": "k"}}, "max_chars": 1000})

    output, _ = _fetch(tool, "https://example.com/long", {"title": "Long", "content": "x" * 1500})

    page = json.loads(output)
    assert page["content"] == "x" * 1000
    assert page["truncated"] is True
    assert page["total_chars"] == 1500
    assert "1500" in page["note"]


def test_content_equal_to_limit_is_not_truncated():
    tool = _build({"type": "deepseek", "config": {"deepseek": {"api_key": "k"}}, "max_chars": 1000})

    output, _ = _fetch(tool, "https://example.com/exact", {"title": "Exact", "content": "y" * 1000})

    page = json.loads(output)
    assert page["truncated"] is False
    assert "note" not in page


def test_max_chars_is_clamped_to_allowed_range():
    small = _build({"type": "deepseek", "config": {"deepseek": {"api_key": "k"}}, "max_chars": 10})
    large = _build({"type": "deepseek", "config": {"deepseek": {"api_key": "k"}}, "max_chars": "999999"})

    assert small.max_chars == 1000
    assert large.max_chars == 200000


def test_invalid_urls_do_not_call_engine():
    tool = _build()

    for url in ("ftp://example.com/a", "example.com/a", "https://user:pass@example.com/a", "http://"):
        with patch.object(web_fetch_tool.requests, "post") as call:
            output = tool.invoke({"url": url})
        call.assert_not_called()
        assert output.startswith("网页读取失败")


def test_engine_error_is_returned_as_text():
    payload = {
        "error": {
            "message": "failed to fetch URL (request_id: abc)",
            "type": "not_found_error",
            "param": None,
            "code": "invalid_request_error",
        }
    }

    output, _ = _fetch(_build(), "https://en.wikipedia.org/wiki/Taiwan", payload, status_code=404)

    assert output.startswith("网页读取失败")
    assert "failed to fetch URL" in output


def test_timeout_is_returned_as_text():
    tool = _build()

    with patch.object(web_fetch_tool.requests, "post", side_effect=requests.Timeout("read timed out")):
        output = tool.invoke({"url": "https://example.com/slow"})

    assert output.startswith("网页读取失败")


def test_empty_content_is_reported():
    output, _ = _fetch(_build(), "https://example.com/empty", {"title": "Empty", "content": "  \n"})

    assert output == "该网页没有可读正文。"


def test_unconfigured_tool_still_builds_and_reports():
    for extra in ({}, {"type": "deepseek", "config": {"deepseek": {"api_key": ""}}}):
        tool = _build(extra)
        with patch.object(web_fetch_tool.requests, "post") as call:
            output = tool.invoke({"url": "https://example.com/a"})
        call.assert_not_called()
        assert output.startswith("网页读取尚未配置")

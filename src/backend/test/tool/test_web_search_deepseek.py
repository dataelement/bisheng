"""DeepSeek web search maps its results onto the shared web search protocol.

The citation registry reads that protocol, so a field mapped wrong here shows
up as a citation card without a title, source or date.
"""

import json
from unittest.mock import MagicMock, patch

from bisheng.citation.domain.services.citation_prompt_helper import annotate_web_results_with_citations
from bisheng_langchain.gpts.tools.web_search import tool as web_search_tool
from bisheng_langchain.gpts.tools.web_search.tool import DeepSeekSearch, SearchTool

DEEPSEEK_PAYLOAD = {
    "results": [
        {
            "rerank_score": 2.4,
            "title": "DeepSeek V4 模型发布",
            "url": "https://example.com/deepseek-v4",
            "snippet": "DeepSeek V4 已上线。",
            "summary": "DeepSeek 发布了 V4 模型，改进了工具调用与长上下文能力。",
            "content": "",
            "site_name": "Example News",
            "site_icon": "https://example.com/favicon.ico",
            "date": "2026-06-01T00:00:00+00:00",
            "authority": 3,
        },
        {
            "rerank_score": 1.1,
            "title": "No snippet page",
            "url": "https://other.example.org/page",
            "snippet": "",
            "summary": "Long abstract only.",
            "content": "",
            "site_name": None,
            "site_icon": None,
            "date": None,
            "authority": -1,
        },
    ]
}


def _ok_response(payload):
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


def _search(payload=DEEPSEEK_PAYLOAD, **config):
    search = SearchTool.init_search_tool("deepseek", **({"api_key": "sk-test"} | config))
    with patch.object(web_search_tool.requests, "post", return_value=_ok_response(payload)) as call:
        output = search.invoke("DeepSeek V4")
    return search, call, json.loads(output)


def test_request_uses_bearer_key_and_default_endpoint():
    search, call, _ = _search()

    assert isinstance(search, DeepSeekSearch)
    assert call.call_args.args[0] == "https://api.deepseek.com/v1/tools/search"
    assert call.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert call.call_args.kwargs["json"]["query"] == "DeepSeek V4"


def test_base_url_override():
    _, call, _ = _search(base_url="https://proxy.example.com/ds/search")

    assert call.call_args.args[0] == "https://proxy.example.com/ds/search"


def test_results_are_normalized():
    _, _, results = _search()

    first, second = results
    assert first["title"] == "DeepSeek V4 模型发布"
    assert first["url"] == "https://example.com/deepseek-v4"
    assert first["snippet"] == "DeepSeek V4 已上线。"
    assert first["source"] == "Example News"
    assert first["siteIcon"] == "https://example.com/favicon.ico"
    assert first["datePublished"] == "2026-06-01T00:00:00+00:00"
    # Missing snippet falls back to the long summary; missing site name to the host.
    assert second["snippet"] == "Long abstract only."
    assert second["source"] == "other.example.org"
    assert second["siteIcon"] is None
    assert second["datePublished"] is None


def test_results_get_citation_keys():
    _, _, results = _search()

    annotated = annotate_web_results_with_citations(results)

    keys = [item["citation_key"] for item in annotated]
    assert len(keys) == 2
    assert all(key.startswith("websearch_") and ":" in key for key in keys)
    assert len(set(keys)) == 2

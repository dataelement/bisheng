"""Every search provider request carries a timeout.

Without one, an endpoint that accepts the connection but never answers (a common
intranet proxy behaviour) blocks the calling agent forever.
"""

from unittest.mock import MagicMock, patch

import pytest

from bisheng_langchain.gpts.tools.web_search import tool as web_search_tool
from bisheng_langchain.gpts.tools.web_search.tool import SearchTool


def _ok_response(payload):
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


@pytest.mark.parametrize(
    ("provider", "config", "method", "payload"),
    [
        ("bocha", {"api_key": "k"}, "post", {"code": 200, "data": {"webPages": {"value": []}}}),
        ("tavily", {"api_key": "k"}, "post", {"results": []}),
        ("serp", {"api_key": "k"}, "get", {"organic_results": []}),
        ("cloudsway", {"api_key": "k", "base_url": "https://cs.example.com"}, "get", {"webPages": {"value": []}}),
        ("searXNG", {"base_url": "https://searx.example.com"}, "get", {"results": []}),
    ],
)
def test_provider_request_has_default_timeout(provider, config, method, payload):
    search = SearchTool.init_search_tool(provider, **config)

    with patch.object(web_search_tool.requests, method, return_value=_ok_response(payload)) as call:
        search.invoke("信托公司")

    assert call.call_args.kwargs["timeout"] == (10, 60)


def test_jina_deepsearch_gets_a_longer_read_timeout():
    search = SearchTool.init_search_tool("jina", api_key="k")

    with patch.object(web_search_tool.requests, "post", return_value=_ok_response({"choices": []})) as call:
        search.invoke("信托公司")

    assert call.call_args.kwargs["timeout"] == (10, 300)

"""Xiaosu (小宿科技) provider contract.

The request shape is ported from the reference Go client
(``internal/infrastructure/web_search/xiaosu.go``): a bearer-authenticated
``GET /search/{endpoint}/smart`` whose response nests the hits under
``webPages.value``.
"""

import json
from unittest.mock import MagicMock, patch

from bisheng_langchain.gpts.tools.web_search import tool as web_search_tool
from bisheng_langchain.gpts.tools.web_search.tool import SearchTool


def _ok_response(payload):
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    return response


def test_xiaosu_builds_the_reference_url_and_params():
    search = SearchTool.init_search_tool("xiaosu", api_key="k")
    payload = {
        "webPages": {
            "value": [
                {
                    "id": 1,
                    "name": "标题",
                    "url": "https://example.com/a",
                    "snippet": "摘要",
                    "datePublished": "2026-05-19T01:47:00.0000000",
                    "siteName": "示例站点",
                }
            ]
        }
    }

    with patch.object(web_search_tool.requests, "get", return_value=_ok_response(payload)) as call:
        raw = search.invoke("信托公司")

    assert call.call_args.args[0] == ("https://searchapi.xiaosuai.com/search/AOLwWFjoedCbmysb/smart")
    kwargs = call.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer k"}
    assert kwargs["params"]["q"] == "信托公司"
    assert kwargs["params"]["count"] == 10
    assert kwargs["params"]["mainText"] == "true"
    assert kwargs["params"]["enableContent"] == "true"
    assert kwargs["params"]["contentType"] == "TEXT"
    assert kwargs["timeout"] == (10, 60)

    items = json.loads(raw)
    assert items[0]["title"] == "标题"
    assert items[0]["url"] == "https://example.com/a"
    assert items[0]["snippet"] == "摘要"
    assert items[0]["source"] == "示例站点"
    assert items[0]["datePublished"] == "2026-05-19T01:47:00.0000000"


def test_xiaosu_honours_custom_base_path_and_endpoint():
    search = SearchTool.init_search_tool(
        "xiaosu",
        api_key="k",
        base_path="https://search.example.com/",
        endpoint="custom-endpoint",
    )

    with patch.object(web_search_tool.requests, "get", return_value=_ok_response({"webPages": {"value": []}})) as call:
        search.invoke("q")

    assert call.call_args.args[0] == ("https://search.example.com/search/custom-endpoint/smart")

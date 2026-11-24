"""Blank optional parameters are omitted instead of being sent as "".

Regression: the tool test dialog sent every unfilled parameter as "". The legacy
mapper kept "" for an optional integer (conversion failed silently), so the
upstream received `"count": ""` and rejected the request with HTTP 400.
The same mapper runs for assistants and workflows, so these tests also pin
the unchanged behaviour for filled and required values.
"""

import pytest

from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools


def tool(parameters):
    return OpenApiTools(
        url="https://fixture.example",
        params={"path": "/v1/tools/search", "method": "post", "parameters": parameters},
    )


def param(name, field_type, location="body", required=False):
    return {"name": name, "in": location, "required": required, "schema": {"type": field_type}}


SEARCH_PARAMS = [
    param("query", "string", required=True),
    param("count", "integer"),
    param("ori_question", "string"),
    param("need_content", "boolean"),
    param("ratio", "number"),
    param("tags", "array"),
    param("filters", "object"),
    param("page", "integer", location="query"),
]


def test_blank_optional_non_string_values_are_omitted():
    supplied = {
        "query": "bisheng",
        "count": "",
        "need_content": "",
        "ratio": "",
        "tags": "",
        "filters": "",
        "page": "",
    }
    assert tool(SEARCH_PARAMS).get_params_json(**supplied) == ({}, {"query": "bisheng"}, {})


def test_blank_optional_string_value_is_kept():
    # "" is a valid string value, so the mapper cannot treat it as "not provided".
    _, body, _ = tool(SEARCH_PARAMS).get_params_json(query="bisheng", ori_question="")
    assert body == {"query": "bisheng", "ori_question": ""}


@pytest.mark.parametrize(
    ("field_type", "expected"),
    [("integer", ""), ("number", ""), ("boolean", False), ("string", "")],
)
def test_blank_required_values_keep_previous_behaviour(field_type, expected):
    # Required values are never dropped; the upstream reports the missing value.
    parameters = [param("value", field_type, required=True)]
    assert tool(parameters).get_params_json(value="") == ({}, {"value": expected}, {})


def test_blank_path_parameter_is_kept():
    parameters = [{"name": "item_id", "in": "path", "schema": {"type": "integer"}}]
    assert tool(parameters).get_params_json(item_id="") == ({}, {}, {"item_id": ""})


def test_filled_values_are_converted_as_before():
    supplied = {
        "query": "bisheng",
        "count": "5",
        "ori_question": "what is bisheng",
        "need_content": "true",
        "ratio": "0.5",
        "tags": '["a", "b"]',
        "filters": '{"lang": "zh"}',
        "page": "2",
    }
    assert tool(SEARCH_PARAMS).get_params_json(**supplied) == (
        {"page": 2},
        {
            "query": "bisheng",
            "count": 5,
            "ori_question": "what is bisheng",
            "need_content": True,
            "ratio": 0.5,
            "tags": ["a", "b"],
            "filters": {"lang": "zh"},
        },
        {},
    )


def test_typed_falsy_values_from_a_model_are_not_dropped():
    supplied = {"query": "bisheng", "count": 0, "need_content": False, "tags": []}
    assert tool(SEARCH_PARAMS).get_params_json(**supplied) == ({}, supplied, {})


def test_undeclared_blank_value_is_passed_through_unchanged():
    assert tool(SEARCH_PARAMS).get_params_json(query="bisheng", extra="") == (
        {"extra": ""},
        {"query": "bisheng"},
        {},
    )


async def test_imported_schema_to_outgoing_body_omits_blank_optional_fields():
    """Imported schema -> tool build (as /tool/test and ToolExecutor do) -> outgoing JSON body."""
    import json
    from unittest.mock import AsyncMock

    from bisheng.tool.domain.services.openapi import OpenApiSchema
    from bisheng.tool.domain.services.tool import ToolServices

    schema = {
        "openapi": "3.0.1",
        "info": {"title": "search", "version": "1.0.0"},
        "servers": [{"url": "https://fixture.example"}],
        "paths": {
            "/v1/tools/search": {
                "post": {
                    "operationId": "web_search",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["query"],
                                    "properties": {
                                        "query": {"type": "string"},
                                        "count": {"type": "integer", "default": 10},
                                        "need_content": {"type": "boolean", "default": False},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    tool_type = await ToolServices.parse_openapi_schema(None, json.dumps(schema))
    extra = json.loads(tool_type.children[0].extra)
    extra.update({"api_location": None, "parameter_name": None})
    tool_params = OpenApiSchema.parse_openapi_tool_params("test", "test", json.dumps(extra), tool_type.server_host, 0)
    client = AsyncMock()
    client.apost.return_value = "ok"
    api_tool = OpenApiTools.get_api_tool("test", async_client=client, **tool_params)
    # Same payload shape the test dialog sent before the frontend fix.
    assert await api_tool.arun({"query": "bisheng", "count": "", "need_content": ""}) == "ok"
    assert client.apost.await_args.kwargs["json"] == {"query": "bisheng"}

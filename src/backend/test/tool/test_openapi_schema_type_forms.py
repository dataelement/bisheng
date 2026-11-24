"""Common OpenAPI type forms build a tool instead of failing with HTTP 500.

Before the fix, OpenApiTools read ``schema["type"]`` and ``schema["properties"]``
directly, so three forms that the schema importer accepts failed later, when the
tool test or an assistant/workflow built the tool:

- a parameter with only ``anyOf``/``oneOf`` (KeyError: 'type')
- an OpenAPI 3.1 type array such as ``["integer", "null"]`` (TypeError)
- ``type: object`` without ``properties`` (KeyError: 'properties')
"""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from bisheng_langchain.utils.openapi import has_null_member, resolve_openapi_type


def body_param(name, schema, required=False):
    return {"name": name, "in": "body", "required": required, "description": name, "schema": schema}


def build(parameters, **kwargs):
    return OpenApiTools(
        url="https://fixture.example",
        params={"path": "/submit", "method": "post", "parameters": parameters},
        **kwargs,
    )


@pytest.mark.parametrize(
    ("schema", "expected_type", "nullable"),
    [
        ({"type": "integer"}, "integer", False),
        ({"type": ["integer", "null"]}, "integer", True),
        ({"type": ["null", "string"]}, "string", True),
        ({"type": ["string", "integer"]}, None, False),
        ({"anyOf": [{"type": "integer"}, {"type": "null"}]}, "integer", True),
        ({"oneOf": [{"type": "number"}, {"type": "number", "minimum": 1}]}, "number", False),
        ({"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}, None, False),
        ({"anyOf": [{"type": ["boolean", "null"]}]}, "boolean", False),
        ({"description": "no type at all"}, None, False),
    ],
)
def test_resolve_openapi_type(schema, expected_type, nullable):
    assert resolve_openapi_type(schema) == expected_type
    assert has_null_member(schema) is nullable


def test_type_array_with_null_maps_to_nullable_concrete_type():
    tool = build([body_param("count", {"type": ["integer", "null"]})])
    assert tool.parse_args_schema()["properties"]["count"] == {"description": "count", "type": ["integer", "null"]}
    assert tool.get_params_json(count="5") == ({}, {"count": 5}, {})
    assert tool.get_params_json(count=None) == ({}, {"count": None}, {})


@pytest.mark.parametrize("union", ["anyOf", "oneOf"])
def test_union_with_single_concrete_branch_maps_to_that_type(union):
    tool = build([body_param("count", {union: [{"type": "integer"}, {"type": "null"}]})])
    assert tool.parse_args_schema()["properties"]["count"] == {"description": "count", "type": ["integer", "null"]}
    assert tool.get_params_json(count="7") == ({}, {"count": 7}, {})


def test_union_with_different_types_is_untyped_and_not_coerced():
    # e.g. a `stop` field that accepts a string or a list of strings.
    schema = {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}
    tool = build([body_param("stop", schema)])
    assert tool.parse_args_schema()["properties"]["stop"] == {"description": "stop"}
    assert tool.get_params_json(stop=["a", "b"]) == ({}, {"stop": ["a", "b"]}, {})
    assert tool.get_params_json(stop="a") == ({}, {"stop": "a"}, {})
    # An untyped value may be a string, so a blank value is kept.
    assert tool.get_params_json(stop="") == ({}, {"stop": ""}, {})


def test_object_without_properties_accepts_any_dict():
    tool = build([body_param("filters", {"type": "object"})])
    assert tool.parse_args_schema()["properties"]["filters"] == {
        "description": "filters",
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    assert tool.get_params_json(filters='{"lang": "zh"}') == ({}, {"filters": {"lang": "zh"}}, {})
    assert tool.get_params_json(filters={"lang": "zh"}) == ({}, {"filters": {"lang": "zh"}}, {})


def test_object_property_with_union_type_builds():
    schema = {"type": "object", "properties": {"limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}}
    tool = build([body_param("options", schema)])
    assert tool.parse_args_schema()["properties"]["options"]["properties"] == {"limit": {"type": ["integer", "null"]}}


def test_args_schema_is_standard_json_schema():
    """Arguments sit under "properties"; items, nested fields and nullable use standard JSON Schema."""
    parameters = [
        body_param("query", {"type": "string"}, required=True),
        body_param("count", {"type": "integer", "nullable": True}),
        body_param("tags", {"type": "array", "items": {"type": "integer"}}),
        body_param("raw", {"type": "array"}),
        body_param(
            "opts",
            {
                "type": "object",
                "items": {"type": "number"},
                "required": ["a", "missing"],
                "properties": {
                    "a": {"type": "string", "description": "field a"},
                    "b": {"type": "array", "items": {"type": "number"}},
                    "c": {"type": "object"},
                    "d": {"type": "file"},
                },
            },
        ),
        body_param("legacy", {"type": "dict", "properties": {}}),
        body_param(
            "rows",
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer", "description": "row id"},
                        "labels": {"type": "array", "items": {"type": "string", "nullable": True}},
                    },
                },
            },
        ),
    ]
    assert build(parameters).parse_args_schema() == {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "query"},
            "count": {"type": ["integer", "null"], "description": "count"},
            "tags": {"type": "array", "items": {"type": "integer"}, "description": "tags"},
            "raw": {"type": "array", "items": {"type": "string"}, "description": "raw"},
            "opts": {
                "type": "object",
                "description": "opts",
                "required": ["a"],
                "properties": {
                    "a": {"type": "string", "description": "field a"},
                    "b": {"type": "array", "items": {"type": "number"}},
                    "c": {"type": "object", "properties": {}, "additionalProperties": True},
                    "d": {},
                },
            },
            "legacy": {"type": "object", "description": "legacy", "properties": {}},
            "rows": {
                "type": "array",
                "description": "rows",
                "items": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer", "description": "row id"},
                        "labels": {"type": "array", "items": {"type": ["string", "null"]}},
                    },
                },
            },
        },
    }


def test_nullable_keyword_passes_null_through():
    # The model is told that null is allowed, so null is sent as null (not coerced to False).
    tool = build([body_param("flag", {"type": "boolean", "nullable": True})])
    assert tool.parse_args_schema()["properties"]["flag"]["type"] == ["boolean", "null"]
    assert tool.get_params_json(flag=None) == ({}, {"flag": None}, {})
    assert tool.get_params_json(flag="true") == ({}, {"flag": True}, {})


def test_unknown_scalar_type_is_still_rejected():
    with pytest.raises(Exception, match="schema type is not support: file"):
        build([body_param("upload", {"type": "file"})]).parse_args_schema()


PLATFORM_31_EXAMPLE_STYLE = {
    "openapi": "3.1.0",
    "info": {"title": "Search", "description": "Search the web.", "version": "v1.0.0"},
    "servers": [{"url": "https://search.example.com"}],
    "paths": {
        "/search": {
            "post": {
                "summary": "",
                "description": "Search the web",
                "operationId": "Search",
                "parameters": [
                    {
                        "name": "page",
                        "in": "query",
                        "description": "Page number",
                        "required": False,
                        "schema": {"type": ["integer", "null"]},
                    }
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {
                                    "query": {"type": "string", "description": "Search words"},
                                    "count": {
                                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                                        "description": "Result count",
                                    },
                                    "stop": {
                                        "oneOf": [
                                            {"type": "string"},
                                            {"type": "array", "items": {"type": "string"}},
                                        ]
                                    },
                                    "filters": {"type": "object", "description": "Free-form filters"},
                                },
                            }
                        }
                    }
                },
                "deprecated": False,
            }
        }
    },
    "components": {"schemas": {}},
}


async def test_platform_31_example_style_schema_imports_builds_and_runs():
    from bisheng.tool.domain.services.openapi import OpenApiSchema
    from bisheng.tool.domain.services.tool import ToolServices

    tool_type = await ToolServices.parse_openapi_schema(None, json.dumps(PLATFORM_31_EXAMPLE_STYLE))
    extra = json.loads(tool_type.children[0].extra)
    extra.update({"api_location": None, "parameter_name": None})
    tool_params = OpenApiSchema.parse_openapi_tool_params("test", "test", json.dumps(extra), tool_type.server_host, 0)
    client = AsyncMock()
    client.apost.return_value = "ok"
    # The same factory that ToolExecutor uses for saved API tools.
    api_tool = OpenApiTools.get_api_tool("Search", async_client=client, **tool_params)

    assert api_tool.args_schema["required"] == ["query"]
    args = api_tool.args_schema["properties"]
    assert args["page"] == {"description": "Page number", "type": ["integer", "null"]}
    assert args["count"] == {"description": "Result count", "type": ["integer", "null"]}
    assert args["stop"] == {"description": ""}
    assert args["filters"]["additionalProperties"] is True
    parameters = convert_to_openai_tool(api_tool)["function"]["parameters"]
    assert parameters["properties"] == args
    assert set(parameters) == {"type", "properties", "required"}

    supplied = {"query": "bisheng", "page": "2", "count": "", "stop": ["\n"], "filters": '{"lang": "zh"}'}
    assert await api_tool.arun(supplied) == "ok"
    call = client.apost.await_args
    assert call.args == ("https://search.example.com/search",)
    assert call.kwargs["params"] == {"page": 2}
    assert call.kwargs["json"] == {"query": "bisheng", "stop": ["\n"], "filters": {"lang": "zh"}}

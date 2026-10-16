"""API argument validation and destination boundaries; no tool persistence tests."""

import json
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolUnsupportedError
from bisheng.tool.domain.services.saved_schema import SavedToolSchema, validate_destination


def saved_schema(properties=None, **schema_options):
    properties = properties or {"query": {"type": "string", "enum": ["yes", "no"]}}
    operation = {
        "operationId": "search",
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                        **schema_options,
                    }
                }
            }
        },
    }
    document = {"openapi": "3.0.3", "paths": {"/search": {"post": operation}}}
    params = [
        {"name": name, "in": "body", "required": True, "schema": {"type": spec["type"]}}
        for name, spec in properties.items()
    ]
    tool = SimpleNamespace(name="search", extra=json.dumps({"path": "/search", "method": "post", "parameters": params}))
    category = SimpleNamespace(openapi_schema=json.dumps(document), server_host="https://search.example", extra="{}")
    return tool, category


def test_saved_enum_required_and_extras():
    """AC-13, AC-14: full schema constraints survive the imported representation."""
    schema = SavedToolSchema.from_saved(*saved_schema())
    assert schema.validate({"query": "yes"}) == {"query": "yes"}
    for value in ({}, {"query": "invalid"}, {"query": True}, {"query": "yes", "proxy": "secret"}):
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate(value)


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "object"},
        {"type": "array"},
        {"type": "string", "pattern": ".*"},
        {"type": "string", "nullable": True},
        {"oneOf": [{"type": "string"}]},
    ],
)
def test_api_rejects_unsupported_schema(spec):
    """AC-05: unsupported constraints are not silently discarded."""
    tool, category = saved_schema({"query": {"type": "string"}})
    doc = json.loads(category.openapi_schema)
    doc["paths"]["/search"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["query"] = (
        spec
    )
    category.openapi_schema = json.dumps(doc)
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(tool, category)


def test_declared_string_and_numeric_bounds():
    """AC-14, AC-22: input bounds come from OpenAPI, without query normalization."""
    schema = SavedToolSchema.from_saved(
        *saved_schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 8},
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 30},
            }
        )
    )
    arguments = {"query": " hello ", "maxResults": 30}
    assert schema.validate(arguments) == arguments
    for invalid in (
        {"query": "", "maxResults": 1},
        {"query": "123456789", "maxResults": 1},
        {"query": "x", "maxResults": 31},
        {"query": "x", "maxResults": True},
    ):
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate(invalid)


def test_strict_integer_and_reserved_arguments():
    """AC-14, AC-15: booleans/floats are not integers; wrapper controls are not inputs."""
    schema = SavedToolSchema.from_saved(*saved_schema({"count": {"type": "integer", "minimum": 1}}))
    for value in (True, 1.0, "1", 0):
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate({"count": value})
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved_schema({"proxy": {"type": "string"}}))


@pytest.mark.parametrize(
    "url",
    [
        "https://alias/api/v1/dsh/tools/bs_web_search/invoke",
        "https://host/a/../b",
        "https://user:password@host/search",
        "file:///search",
        "https://host/%2e%2e/search",
        "https://host/{path}",
        "https://host/search?token=secret",
    ],
)
def test_destination_rejects_recursion_and_ambiguity(url):
    """AC-31: aliases and ambiguous destinations cannot recursively invoke the API."""
    with pytest.raises(DshToolUnsupportedError):
        validate_destination(url)

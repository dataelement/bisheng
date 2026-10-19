"""Bounded nested OpenAPI validation; protocol fields remain caller-owned."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolUnsupportedError
from bisheng.tool.domain.services.saved_schema import SavedToolSchema


def saved(root, *, components=None, body_schema=None, parameters=None):
    body = {"content": {"application/json": {"schema": body_schema or root}}}
    document = {"openapi": "3.0.3", "paths": {"/submit": {"post": {"operationId": "submit", "requestBody": body}}}}
    if components is not None:
        document["components"] = {"schemas": components}
    params = (
        parameters
        if parameters is not None
        else [
            {"name": name, "in": "body", "required": name in root.get("required", []), "schema": spec}
            for name, spec in root.get("properties", {}).items()
        ]
    )
    tool = SimpleNamespace(name="submit", extra=json.dumps({"path": "/submit", "method": "post", "parameters": params}))
    category = SimpleNamespace(openapi_schema=json.dumps(document), server_host="https://tool.example", extra="{}")
    return tool, category


def nested_root():
    return {
        "type": "object",
        "required": ["batch"],
        "properties": {
            "batch": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "minProperties": 2,
                    "maxProperties": 3,
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 5},
                        "count": {"type": "integer", "minimum": 1, "maximum": 3},
                        "enabled": {"type": "boolean", "default": True},
                    },
                    "required": ["text", "count"],
                    "additionalProperties": False,
                },
            },
            "optional": {"type": "string", "default": "must-not-be-inserted"},
        },
    }


def test_nested_constraints_preserve_values_and_never_insert_defaults():
    tool, category = saved(nested_root())
    before = (tool.extra, category.openapi_schema)
    schema = SavedToolSchema.from_saved(tool, category)
    value = {"batch": [{"text": " x ", "count": 2}]}
    untouched = copy.deepcopy(value)
    assert schema.validate(value) == untouched
    assert value == untouched
    assert schema.validate(value)["batch"][0]["count"] is value["batch"][0]["count"]
    assert (tool.extra, category.openapi_schema) == before


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"batch": []},
        {"batch": [{"text": "x", "count": 1}] * 3},
        {"batch": {}},
        {"batch": ["x"]},
        {"batch": [{"text": "x"}]},
        {"batch": [{"text": "", "count": 1}]},
        {"batch": [{"text": "123456", "count": 1}]},
        {"batch": [{"text": "x", "count": 0}]},
        {"batch": [{"text": "x", "count": 4}]},
        {"batch": [{"text": "x", "count": True}]},
        {"batch": [{"text": "x", "count": 1.0}]},
        {"batch": [{"text": "x", "count": "1"}]},
        {"batch": [{"text": False, "count": 1}]},
        {"batch": [{"text": "x", "count": 1, "enabled": "true"}]},
        {"batch": [{"text": "x", "count": 1, "extra": 2}]},
        {"batch": [{"text": "x", "count": 1}], "extra": True},
    ],
)
def test_invalid_nested_arguments_are_rejected_without_coercion(value):
    schema = SavedToolSchema.from_saved(*saved(nested_root()))
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate(value)


@pytest.mark.parametrize("additional", [False, True, {"type": "integer", "minimum": 1}])
def test_explicit_nested_additional_properties_are_honored(additional):
    root = {
        "type": "object",
        "properties": {
            "labels": {
                "type": "object",
                "properties": {},
                "additionalProperties": additional,
            }
        },
    }
    schema = SavedToolSchema.from_saved(*saved(root))
    assert schema.validate({"labels": {}}) == {"labels": {}}
    if additional is False:
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate({"labels": {"a": 2}})
    else:
        assert schema.validate({"labels": {"a": 2}}) == {"labels": {"a": 2}}
        if isinstance(additional, dict):
            for value in (0, True, "1"):
                with pytest.raises(DshToolArgumentsInvalidError):
                    schema.validate({"labels": {"a": value}})


def test_undeclared_nested_additional_properties_follow_openapi_default():
    root = {"type": "object", "properties": {"labels": {"type": "object", "properties": {}}}}
    supplied = {"labels": {"caller_owned": 1}}
    assert SavedToolSchema.from_saved(*saved(root)).validate(supplied) == supplied


@pytest.mark.parametrize("additional", [True, {"type": "string"}])
def test_top_level_open_ended_arguments_remain_unsupported(additional):
    root = nested_root()
    root["additionalProperties"] = additional
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root))


def test_schema_refs_at_root_properties_and_array_items_resolve_locally():
    item = {"type": "object", "properties": {"amount": {"$ref": "#/components/schemas/Count"}}, "required": ["amount"]}
    root = {
        "type": "object",
        "properties": {"batch": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}},
    }
    components = {"Root": root, "Item": item, "Count": {"type": "integer", "minimum": 2}}
    schema = SavedToolSchema.from_saved(
        *saved(root, components=components, body_schema={"$ref": "#/components/schemas/Root"})
    )
    assert schema.validate({"batch": [{"amount": 3}]}) == {"batch": [{"amount": 3}]}
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"batch": [{"amount": 1}]})
    assert "$ref" not in json.dumps(schema.schema)


def test_shared_local_refs_are_not_mistaken_for_cycles_and_decode_json_pointer():
    ref = {"$ref": "#/components/schemas/a~1b~0c"}
    root = {"type": "object", "properties": {"first": ref, "second": ref}}
    schema = SavedToolSchema.from_saved(*saved(root, components={"a/b~c": {"type": "integer"}}))
    assert schema.validate({"first": 1, "second": 2}) == {"first": 1, "second": 2}


@pytest.mark.parametrize(
    "spec",
    [
        {"$ref": "https://untrusted.invalid/schema.json"},
        {"$ref": "file:///etc/passwd"},
        {"$ref": "#/components/schemas/Missing"},
        {"$ref": "#/components/schemas/bad~2escape"},
        {"$ref": "#/components/schemas/Node", "type": "object"},
        {"oneOf": [{"type": "integer"}, {"type": "string"}]},
        {"type": "object", "allOf": []},
        {"type": "string", "pattern": ".*"},
        {"type": "array"},
        {"type": "array", "items": [{"type": "integer"}]},
        {"type": "array", "items": {"type": "integer"}, "contains": {"type": "integer"}},
        {"type": "object", "patternProperties": {}},
        {"type": "string", "properties": {"bad": {"type": "integer"}}},
    ],
)
def test_unsupported_nested_schema_features_fail_closed(spec):
    root = {"type": "object", "properties": {"data": spec}}
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root, components={"Node": {"type": "object"}}))


def test_recursive_local_references_are_rejected():
    node = {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/Node"}}}
    root = {"type": "object", "properties": {"tree": {"$ref": "#/components/schemas/Node"}}}
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root, components={"Node": node}))


def test_reference_alias_chain_depth_is_bounded():
    components = {"Node0": {"type": "string"}}
    for i in range(1, 20):
        components[f"Node{i}"] = {"$ref": f"#/components/schemas/Node{i - 1}"}
    root = {"type": "object", "properties": {"data": {"$ref": "#/components/schemas/Node19"}}}
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root, components=components))


def test_reference_expansion_node_count_is_bounded():
    components = {"Node0": {"type": "string"}}
    for i in range(1, 11):
        ref = {"$ref": f"#/components/schemas/Node{i - 1}"}
        components[f"Node{i}"] = {"type": "object", "properties": {"a": ref, "b": ref}}
    root = {"type": "object", "properties": {"data": {"$ref": "#/components/schemas/Node10"}}}
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root, components=components))


def test_input_size_depth_and_node_count_remain_bounded():
    root = {"type": "object", "properties": {"data": {"type": "object", "additionalProperties": True}}}
    schema = SavedToolSchema.from_saved(*saved(root))
    deep = {}
    for _ in range(40):
        deep = {"child": deep}
    for data in ({"large": "x" * 65536}, {"many": list(range(10000))}, deep):
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate({"data": data})


def test_actual_imported_protocol_fixture_is_accepted_without_generated_or_default_fields():
    fixture = json.loads((Path(__file__).parent / "fixtures/nested_openapi_input.json").read_text())
    root = fixture["requestBody"]["content"]["application/json"]["schema"]
    schema = SavedToolSchema.from_saved(*saved(root, parameters=fixture["parameters"]))
    supplied = {"id": "client-owned-not-generated", "commands": {"search_query": [{"q": " exact query "}]}}
    assert schema.validate(supplied) == supplied
    assert "model" not in schema.validate(supplied)
    for bad in ({"commands": supplied["commands"]}, {"id": "x", "commands": {"search_query": []}}):
        with pytest.raises(DshToolArgumentsInvalidError):
            schema.validate(bad)


def test_empty_scalar_properties_annotation_is_compatible_but_nonempty_is_not():
    root = {"type": "object", "properties": {"value": {"type": "string", "properties": {}}}}
    assert SavedToolSchema.from_saved(*saved(root)).validate({"value": "same"}) == {"value": "same"}
    root["properties"]["value"]["properties"] = {"child": {"type": "integer"}}
    with pytest.raises(DshToolUnsupportedError):
        SavedToolSchema.from_saved(*saved(root))


@pytest.mark.parametrize("value", [{1: "must-not-be-stringified"}, (1, 2), {1, 2}])
def test_unconstrained_nested_values_still_require_canonical_json_types(value):
    root = {"type": "object", "properties": {"data": {"type": "object", "additionalProperties": True}}}
    schema = SavedToolSchema.from_saved(*saved(root))
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"data": {"value": value}})


def test_required_nested_extra_key_is_valid_when_additional_properties_are_declared():
    root = {
        "type": "object",
        "properties": {"labels": {"type": "object", "required": ["label"], "additionalProperties": {"type": "string"}}},
    }
    schema = SavedToolSchema.from_saved(*saved(root))
    assert schema.validate({"labels": {"label": "value"}}) == {"labels": {"label": "value"}}
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"labels": {}})


@pytest.mark.parametrize("value", [{}, {"a": "x", "b": "x", "c": "x"}])
def test_nested_object_property_count_bounds(value):
    root = {
        "type": "object",
        "properties": {
            "labels": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 2,
                "additionalProperties": True,
            }
        },
    }
    schema = SavedToolSchema.from_saved(*saved(root))
    assert schema.validate({"labels": {"a": "x"}}) == {"labels": {"a": "x"}}
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"labels": value})


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf"), 0, 3])
def test_nested_number_bounds_and_types_do_not_coerce(value):
    root = {
        "type": "object",
        "properties": {
            "numbers": {
                "type": "array",
                "items": {"type": "number", "minimum": 1, "maximum": 2},
            }
        },
    }
    schema = SavedToolSchema.from_saved(*saved(root))
    supplied = {"numbers": [1, 1.5, 2]}
    assert schema.validate(supplied) == supplied
    assert type(schema.validate(supplied)["numbers"][0]) is int
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"numbers": [value]})


@pytest.mark.parametrize("section", ["definitions", "$defs"])
def test_other_supported_local_schema_pointer_roots(section):
    root = {"type": "object", "properties": {"value": {"$ref": f"#/{section}/Value"}}}
    tool, category = saved(root)
    document = json.loads(category.openapi_schema)
    document[section] = {"Value": {"type": "string", "enum": ["allowed"]}}
    category.openapi_schema = json.dumps(document)
    schema = SavedToolSchema.from_saved(tool, category)
    assert schema.validate({"value": "allowed"}) == {"value": "allowed"}
    with pytest.raises(DshToolArgumentsInvalidError):
        schema.validate({"value": "other"})

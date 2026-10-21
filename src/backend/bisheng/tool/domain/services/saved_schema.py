"""Bounded, strict OpenAPI input validation without request transformation."""

import json
import math
import re
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolUnsupportedError
from bisheng.utils.bounded_json import check_tree, strict_json

RESERVED = frozenset({"proxy", "callbacks", "config", "run_manager", "tool_call_id", "self"})
ANNOTATED_KEYS = frozenset(
    {
        "type",
        "title",
        "description",
        "default",
        "example",
        "examples",
        "enum",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
    }
)
OBJECT_KEYS = frozenset(
    {
        "type",
        "title",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "maxProperties",
        "example",
        "examples",
    }
)
StrictValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine_many(
        {
            "integer": lambda _checker, value: type(value) is int,
            # math.isfinite(int) overflows for huge ints; only floats can be non-finite.
            "number": lambda _checker, value: type(value) is int or (type(value) is float and math.isfinite(value)),
        }
    ),
)


def validate_destination(url):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in url
            or any(c.isspace() or ord(c) < 32 for c in url)
            or len(url) > 8192
            or any(c in parsed.path for c in ("%", "{", "}"))
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or "/dsh/tools/" in parsed.path
            or "//" in parsed.path
        ):
            raise ValueError("Invalid destination")
        _ = parsed.port
    except (ValueError, TypeError):
        raise DshToolUnsupportedError() from None
    return url


class _UniqueLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError("Duplicate YAML key")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _document(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 262144:
        raise ValueError("Invalid saved schema")
    value = strict_json(raw) if raw.lstrip().startswith("{") else yaml.load(raw, Loader=_UniqueLoader)
    check_tree(value)
    return value


SCHEMA_REF_PREFIXES = ("#/components/schemas/", "#/definitions/", "#/$defs/")
MAX_SCHEMA_DEPTH = 16
MAX_SCHEMA_NODES = 1024
MAX_INPUT_BYTES = 65536


def _parse_json(value):
    return strict_json(value) if isinstance(value, str) else (value or {})


def _find_operation(document, tool_name, path, method):
    """The saved path/method must be the single operation carrying the tool's operationId."""
    paths = document["paths"]
    matches = [
        (p, m)
        for p, entry in paths.items()
        for m, operation in entry.items()
        if isinstance(operation, dict) and operation.get("operationId") == tool_name
    ]
    if matches != [(path, method)]:
        raise ValueError("Ambiguous saved operation")
    if paths[path].get("parameters") or paths[path][method].get("servers") or document.get("webhooks"):
        raise ValueError("Unsupported operation override")
    return paths[path][method]


def _body_schema(document, operation, method):
    if method == "get" or operation.get("parameters"):
        raise ValueError("Unsupported mixed parameters")
    content = operation["requestBody"]["content"]
    if set(content) != {"application/json"}:
        raise ValueError("Unsupported content type")
    root, _ = _resolve_reference(content["application/json"]["schema"], document, ())
    if root.get("type") != "object":
        raise ValueError("Unsupported body schema")
    required = root.get("required", [])
    parameters = [
        {"name": name, "in": "body", "required": name in required, "schema": spec}
        for name, spec in root.get("properties", {}).items()
    ]
    return dict(root), parameters


def _query_schema(operation):
    properties, required, parameters = {}, [], []
    for param in operation.get("parameters", []):
        if param.get("in") != "query" or param.get("style", "form") != "form" or param.get("content"):
            raise ValueError("Unsupported parameter location")
        name = param["name"]
        if name in properties:
            raise ValueError("Duplicate parameter")
        properties[name] = param["schema"]
        if param.get("required", False):
            required.append(name)
        parameters.append(param)
    return {"type": "object", "properties": properties, "required": required}, parameters


def _resolve_reference(schema, document, active):
    while isinstance(schema, dict) and "$ref" in schema:
        reference = schema["$ref"]
        if (
            set(schema) != {"$ref"}
            or not isinstance(reference, str)
            or not reference.startswith(SCHEMA_REF_PREFIXES)
            or reference in active
            or len(active) >= MAX_SCHEMA_DEPTH
        ):
            raise ValueError("Unsupported schema reference")
        active = (*active, reference)
        target = document
        for token in reference[2:].split("/"):
            if re.search(r"~(?![01])", token):
                raise ValueError("Invalid JSON pointer")
            target = target[token.replace("~1", "/").replace("~0", "~")]
        schema = target
    if not isinstance(schema, dict):
        raise ValueError("Schema must be an object")
    return schema, active


def _tighten(schema, document=None):
    """Compile a bounded local schema; never coerce, default or rewrite inputs."""
    nodes = 0

    def compile_node(spec, depth=0, active=()):
        nonlocal nodes
        spec, references = _resolve_reference(spec, document or {}, active)
        nodes += 1 + len(references) - len(active)
        if depth > MAX_SCHEMA_DEPTH or nodes > MAX_SCHEMA_NODES:
            raise ValueError("Schema complexity limit")
        spec = dict(spec)
        kind = spec.get("type")
        if kind in {"string", "integer", "number", "boolean"}:
            # The legacy importer adds this empty annotation to scalar fields.
            if spec.get("properties") == {}:
                spec.pop("properties")
            if set(spec) - ANNOTATED_KEYS:
                raise ValueError("Unsupported scalar constraints")
            if kind == "string":
                spec["maxLength"] = min(spec.get("maxLength", 4096), 4096)
        elif kind == "object":
            if set(spec) - (OBJECT_KEYS | {"default", "enum"}):
                raise ValueError("Unsupported object constraints")
            properties = spec.get("properties", {})
            if not isinstance(properties, dict) or len(properties) > 32:
                raise ValueError("Unsupported object properties")
            required = spec.get("required", [])
            if (
                not isinstance(required, list)
                or any(not isinstance(name, str) or not name for name in required)
                or (depth == 0 and any(name not in properties for name in required))
                or len(set(required)) != len(required)
            ):
                raise ValueError("Invalid required properties")
            for name in properties:
                if not isinstance(name, str) or not name or (depth == 0 and name in RESERVED):
                    raise ValueError("Unsupported field")
            spec["properties"] = {
                name: compile_node(child, depth + 1, references) for name, child in properties.items()
            }
            additional = spec.get("additionalProperties", depth != 0)
            if depth == 0 and additional is not False:
                raise ValueError("Undeclared top-level inputs are unsupported")
            if isinstance(additional, dict):
                additional = compile_node(additional, depth + 1, references)
            elif type(additional) is not bool:
                raise ValueError("Invalid additional properties")
            spec["additionalProperties"] = additional
            spec["maxProperties"] = min(spec.get("maxProperties", 32), 32)
        elif kind == "array":
            allowed = (ANNOTATED_KEYS - {"minLength", "maxLength", "minimum", "maximum"}) | {
                "items",
                "minItems",
                "maxItems",
            }
            if set(spec) - allowed or not isinstance(spec.get("items"), dict):
                raise ValueError("Unsupported array constraints")
            spec["items"] = compile_node(spec["items"], depth + 1, references)
            spec["maxItems"] = min(spec.get("maxItems", 1000), 1000)
        else:
            raise ValueError("Unsupported schema type")
        for key in ("minLength", "maxLength", "minProperties", "maxProperties", "minItems", "maxItems"):
            if key in spec and (type(spec[key]) is not int or spec[key] < 0):
                raise ValueError("Invalid count constraint")
        if "enum" in spec and (not isinstance(spec["enum"], list) or len(spec["enum"]) > 128):
            raise ValueError("Enum complexity limit")
        return spec

    result = compile_node(schema)
    if result["type"] != "object":
        raise ValueError("Arguments require an object schema")
    StrictValidator.check_schema(result)
    return result


def _signature(parameters, document):
    return sorted(
        (p["name"], p["in"], p.get("required", False), _resolve_reference(p["schema"], document, ())[0]["type"])
        for p in parameters
    )


class SavedToolSchema:
    """Strict argument schema rebuilt from the saved OpenAPI document.

    The importer keeps only name/type for body fields, so constraints such as
    enum and length bounds are recovered from the original document here.
    The bounded subset supports scalars, objects, arrays and local references.
    Nested additionalProperties follows OpenAPI defaults; top-level inputs remain
    closed. Schema expansion and JSON complexity/size are capped, and validation
    never inserts defaults or transforms the caller's protocol.
    """

    def __init__(self, schema):
        self.schema = schema

    def validate(self, arguments):
        try:
            if type(arguments) is not dict:
                raise ValueError("Arguments must be an object")
            check_tree(arguments)
            pending = [arguments]
            while pending:
                item = pending.pop()
                if type(item) is dict:
                    if any(type(key) is not str for key in item):
                        raise ValueError("JSON object keys must be strings")
                    pending.extend(item.values())
                elif type(item) is list:
                    pending.extend(item)
                elif type(item) not in {str, int, float, bool, type(None)}:
                    raise ValueError("Arguments must be JSON values")
            encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > MAX_INPUT_BYTES:
                raise ValueError("Input size limit")
            if next(StrictValidator(self.schema).iter_errors(arguments), None) is not None:
                raise ValueError("Arguments violate schema")
            return dict(arguments)
        except (ValueError, TypeError, RecursionError):
            raise DshToolArgumentsInvalidError() from None

    @classmethod
    def from_saved(cls, tool, category):
        try:
            document = _document(category.openapi_schema)
            if not str(document.get("openapi", "")).startswith("3.0."):
                raise ValueError("Unsupported OpenAPI version")
            extra = _parse_json(tool.extra)
            path, method = extra["path"], extra["method"].lower()
            if method not in {"get", "post", "put", "delete"} or not path.startswith("/"):
                raise ValueError("Unsupported operation")
            validate_destination(category.server_host.rstrip("/") + path)
            operation = _find_operation(document, tool.name, path, method)
            if "requestBody" in operation:
                schema, parameters = _body_schema(document, operation, method)
            else:
                schema, parameters = _query_schema(operation)
            schema = _tighten(schema, document)
            if "requestBody" not in operation and any(
                spec["type"] in {"object", "array"} for spec in schema["properties"].values()
            ):
                raise ValueError("Nested query serialization is unsupported")
            if _signature(parameters, document) != _signature(extra["parameters"], document):
                raise ValueError("Saved operation does not match schema")
            authentication = _parse_json(category.extra)
            # Query credentials cannot be caller-controlled; other wire locations are independent.
            if authentication.get("api_location") == "query" and any(
                parameter["in"] == "query" and parameter["name"] == authentication.get("parameter_name")
                for parameter in parameters
            ):
                raise ValueError("Authentication parameter is not caller controlled")
            return cls(schema)
        except DshToolUnsupportedError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError, SchemaError):
            raise DshToolUnsupportedError() from None

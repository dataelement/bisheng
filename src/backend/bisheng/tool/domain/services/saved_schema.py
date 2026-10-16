"""Faithful flat OpenAPI input validation for existing saved tools."""

import math
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolUnsupportedError
from bisheng.utils.bounded_json import check_tree, strict_json

RESERVED = frozenset({"proxy", "callbacks", "config", "run_manager", "tool_call_id", "self"})
SCALAR_KEYS = frozenset(
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
ROOT_KEYS = frozenset(
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


_SCHEMA_PREFIX = "#/components/schemas/"


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
    root = content["application/json"]["schema"]
    if "$ref" in root:
        name = root["$ref"].removeprefix(_SCHEMA_PREFIX)
        if set(root) != {"$ref"} or name == root["$ref"] or "/" in name:
            raise ValueError("Unsupported schema reference")
        root = document["components"]["schemas"][name]
    if set(root) - ROOT_KEYS or root.get("type") != "object":
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


def _tighten(schema):
    """Accept flat scalar fields only, cap strings, and forbid unknown arguments."""
    properties = schema.get("properties", {})
    if len(properties) > 32 or schema.get("additionalProperties", False) is not False:
        raise ValueError("Unsupported object constraints")
    tightened = {}
    for name, spec in properties.items():
        if name in RESERVED or not name or set(spec) - SCALAR_KEYS:
            raise ValueError("Unsupported field")
        if spec.get("type") not in {"string", "integer", "number", "boolean"}:
            raise ValueError("Unsupported scalar")
        spec = dict(spec)
        if spec["type"] == "string":
            spec["maxLength"] = min(spec.get("maxLength", 4096), 4096)
        tightened[name] = spec
    schema = {**schema, "properties": tightened, "additionalProperties": False}
    StrictValidator.check_schema(schema)
    return schema


def _signature(parameters):
    return sorted((p["name"], p["in"], p.get("required", False), p["schema"]["type"]) for p in parameters)


class SavedToolSchema:
    """Strict argument schema rebuilt from the saved OpenAPI document.

    The importer keeps only name/type for body fields, so constraints such as
    enum and length bounds are recovered from the original document here.
    """

    def __init__(self, schema):
        self.schema = schema

    def validate(self, arguments):
        try:
            if type(arguments) is not dict:
                raise ValueError("Arguments must be an object")
            check_tree(arguments)
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
            schema = _tighten(schema)
            if _signature(parameters) != _signature(extra["parameters"]):
                raise ValueError("Saved operation does not match schema")
            if _parse_json(category.extra).get("parameter_name") in schema["properties"]:
                raise ValueError("Authentication parameter is not caller controlled")
            return cls(schema)
        except DshToolUnsupportedError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError, SchemaError):
            raise DshToolUnsupportedError() from None

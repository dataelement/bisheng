"""Faithful flat OpenAPI input validation for explicitly published saved tools."""

import math
from dataclasses import dataclass
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolPublicationInvalidError
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
            "number": lambda _checker, value: type(value) in {int, float} and math.isfinite(value),
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
        raise DshToolPublicationInvalidError() from None
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


@dataclass(frozen=True)
class PublishedSchema:
    schema: dict
    parameters: list
    destination: str
    method: str

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
            extra = strict_json(tool.extra) if isinstance(tool.extra, str) else tool.extra
            path, method = extra["path"], extra["method"].lower()
            if method not in {"get", "post", "put", "delete"} or not path.startswith("/"):
                raise ValueError("Unsupported operation")
            destination = validate_destination(category.server_host.rstrip("/") + path)
            paths = document["paths"]
            matches = [
                (p, m)
                for p, entry in paths.items()
                for m, operation in entry.items()
                if isinstance(operation, dict) and operation.get("operationId") == tool.name
            ]
            if matches != [(path, method)]:
                raise ValueError("Ambiguous saved operation")
            operation = paths[path][method]
            if paths[path].get("parameters") or operation.get("servers") or document.get("webhooks"):
                raise ValueError("Unsupported operation override")
            parameters = []
            if "requestBody" in operation:
                if method == "get" or operation.get("parameters"):
                    raise ValueError("Unsupported mixed parameters")
                content = operation["requestBody"]["content"]
                if set(content) != {"application/json"}:
                    raise ValueError("Unsupported content type")
                root = content["application/json"]["schema"]
                if "$ref" in root:
                    reference = root["$ref"]
                    prefix = "#/components/schemas/"
                    if set(root) != {"$ref"} or not reference.startswith(prefix) or "/" in reference[len(prefix) :]:
                        raise ValueError("Unsupported schema reference")
                    root = document["components"]["schemas"][reference[len(prefix) :]]
                if set(root) - ROOT_KEYS or root.get("type") != "object":
                    raise ValueError("Unsupported body schema")
                schema = dict(root)
                properties = schema.get("properties", {})
                for name, spec in properties.items():
                    parameters.append(
                        {"name": name, "in": "body", "required": name in schema.get("required", []), "schema": spec}
                    )
            else:
                properties, required = {}, []
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
                schema = {"type": "object", "properties": properties, "required": required}
            if len(properties) > 32 or schema.get("additionalProperties", False) is not False:
                raise ValueError("Unsupported object constraints")
            for name, spec in properties.items():
                if name in RESERVED or not name or set(spec) - SCALAR_KEYS:
                    raise ValueError("Unsupported field")
                if spec.get("type") not in {"string", "integer", "number", "boolean"}:
                    raise ValueError("Unsupported scalar")
                spec = dict(spec)
                if spec["type"] == "string":
                    spec["maxLength"] = min(spec.get("maxLength", 4096), 4096)
                properties = {**properties, name: spec}
            schema = {**schema, "properties": properties, "additionalProperties": False}
            StrictValidator.check_schema(schema)
            saved = extra["parameters"]
            actual = [(p["name"], p["in"], p.get("required", False), p["schema"]["type"]) for p in parameters]
            imported = [(p["name"], p["in"], p.get("required", False), p["schema"]["type"]) for p in saved]
            if sorted(actual) != sorted(imported):
                raise ValueError("Saved operation does not match schema")
            auth = strict_json(category.extra) if isinstance(category.extra, str) else (category.extra or {})
            if auth.get("parameter_name") in properties:
                raise ValueError("Authentication parameter is not caller controlled")
            return cls(schema, parameters, destination, method)
        except DshToolPublicationInvalidError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError, SchemaError):
            raise DshToolPublicationInvalidError() from None

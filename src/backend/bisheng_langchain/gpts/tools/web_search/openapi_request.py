"""Schema-driven search requests. No network, platform imports or provider field names."""

import base64
import copy
import json
import re
from urllib.parse import quote, urlsplit
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .custom import MAX_FIELD_LENGTH, MAX_RESPONSE_BYTES, CustomSearchError, _check_depth, _redact

TRANSPORT_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "accept-encoding",
        "proxy-authorization",
        "proxy-connection",
        "upgrade",
    }
)
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
TOKEN = re.compile(r"\{\{(query|uuid)\}\}")


def validation_schema(schema):
    """Translate OpenAPI 3.0 keywords, preserving property names and literal data."""
    if not isinstance(schema, dict):
        return schema
    result = copy.deepcopy(schema)
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        if isinstance(schema.get(key), dict):
            result[key] = {name: validation_schema(child) for name, child in schema[key].items()}
    for key in (
        "items",
        "additionalProperties",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedProperties",
        "unevaluatedItems",
    ):
        if key in schema:
            result[key] = validation_schema(schema[key])
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(schema.get(key), list):
            result[key] = [validation_schema(child) for child in schema[key]]
    for name in ("Minimum", "Maximum"):
        key, bound = "exclusive" + name, name.lower()
        if type(schema.get(key)) is bool:
            result.pop(key, None)
            if schema[key] and bound in result:
                result[key] = result.pop(bound)
    if schema.get("nullable") is True:
        result.pop("nullable", None)
        return {"anyOf": [result, {"type": "null"}]}
    return result


def validate(value, schema, field):
    try:
        # All references must be resolved locally by the shared loader; never fetch schemas here.
        def local_references(node):
            if isinstance(node, dict):
                for key, child in node.items():
                    if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                        not isinstance(child, str) or not child.startswith("#")
                    ):
                        raise CustomSearchError("External OpenAPI schema references require an authorized import")
                    local_references(child)
            elif isinstance(node, list):
                for child in node:
                    local_references(child)

        local_references(schema)
        converted = validation_schema(schema)
        Draft202012Validator.check_schema(converted)
        if next(Draft202012Validator(converted).iter_errors(value), None) is not None:
            raise CustomSearchError(f"OpenAPI {field} does not match schema")
    except SchemaError:
        raise CustomSearchError(f"Invalid OpenAPI {field} schema") from None


def template_value(schema, depth=0):
    """Produce editable structure, never import example/default values as credentials."""
    if depth > 16 or not isinstance(schema, dict):
        return None
    if schema.get("oneOf") or schema.get("anyOf"):
        return template_value((schema.get("oneOf") or schema["anyOf"])[0], depth + 1)
    if schema.get("allOf"):
        result = {}
        for child in schema["allOf"]:
            value = template_value(child, depth + 1)
            if isinstance(value, dict):
                result.update(value)
        return result
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {
            name: template_value(child, depth + 1)
            for name, child in schema.get("properties", {}).items()
            if name in schema.get("required", [])
        }
    if kind == "array":
        return [
            template_value(schema.get("items", {}), depth + 1)
            for _ in range(min(max(schema.get("minItems", 1), 1), 100))
        ]
    if schema.get("enum"):
        return copy.deepcopy(schema["enum"][0])
    return {"string": "", "integer": 0, "number": 0, "boolean": False}.get(kind)


def request_template(declaration, media_type=None):
    result = {"query": {}, "path": {}, "header": {}, "cookie": {}}
    for param in declaration["parameters"]:
        if param.get("required"):
            result[param["location"]][param["name"]] = template_value(param["schema"])
    bodies = declaration.get("request_body", {}).get("content", {})
    if bodies:
        media_type = media_type or next(iter(bodies))
        result["body"] = template_value(bodies[media_type].get("schema", {}))
    return result


def replace_tokens(value, query):
    if isinstance(value, dict):
        return {key: replace_tokens(child, query) for key, child in value.items()}
    if isinstance(value, list):
        return [replace_tokens(child, query) for child in value]
    if isinstance(value, str):
        return TOKEN.sub(lambda match: query if match[1] == "query" else str(uuid4()), value)
    return value


def _scalar(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def serialize_parameter(param, value):
    """OpenAPI parameter style/explode serialization, retaining repeated query keys."""
    name, location = param["name"], param["location"]
    style = param.get("style") or ("form" if location in {"query", "cookie"} else "simple")
    explode = param.get("explode", style == "form")
    if param.get("content"):
        return [(name, json.dumps(value, ensure_ascii=False, separators=(",", ":")))]
    if style == "deepObject" and isinstance(value, dict):

        def pairs(prefix, item):
            if isinstance(item, dict):
                return [pair for key, child in item.items() for pair in pairs(f"{prefix}[{key}]", child)]
            if isinstance(item, list):
                return [pair for index, child in enumerate(item) for pair in pairs(f"{prefix}[{index}]", child)]
            return [(prefix, _scalar(item))]

        return pairs(name, value)
    if style == "form" and explode:
        if isinstance(value, list):
            return [(name, _scalar(child)) for child in value]
        if isinstance(value, dict):
            return [(key, _scalar(child)) for key, child in value.items()]
    separator = {"spaceDelimited": " ", "pipeDelimited": "|"}.get(style, ",")
    if isinstance(value, dict):
        text = separator.join(
            f"{key}={_scalar(child)}" if explode else f"{key}{separator}{_scalar(child)}"
            for key, child in value.items()
        )
    elif isinstance(value, list):
        text = separator.join(_scalar(child) for child in value)
    else:
        text = _scalar(value)
    if style == "label":
        text = "." + text.replace(",", "." if explode else ",")
    elif style == "matrix":
        text = ";" + (text.replace(",", ";") if isinstance(value, dict) and explode else f"{name}={text}")
    return [(name, text)]


def build_openapi_request(operation, query, api_key=None):
    if not isinstance(query, str) or len(query) > MAX_FIELD_LENGTH:
        raise CustomSearchError("Invalid search request")
    server = urlsplit(operation["server"])
    if (
        server.scheme not in {"http", "https"}
        or not server.hostname
        or server.username is not None
        or server.password is not None
        or server.query
        or server.fragment
        or server.port == 0
    ):
        raise CustomSearchError("Invalid search server")
    if (
        operation["method"] not in METHODS
        or not operation["path"].startswith("/")
        or operation["path"].startswith("//")
        or any(char in operation["path"] for char in "?#\\")
    ):
        raise CustomSearchError("Invalid search operation")
    declaration = operation["declaration"]
    request = replace_tokens(operation.get("request"), query)
    if not isinstance(request, dict) or set(request) - {"query", "path", "header", "cookie", "body"}:
        raise CustomSearchError("Invalid OpenAPI request template")
    _check_depth(request)
    params, headers, cookies = [], {}, []
    path = operation["path"]
    for location in ("query", "path", "header", "cookie"):
        values = request.get(location, {})
        if not isinstance(values, dict):
            raise CustomSearchError("Invalid OpenAPI parameter values")
        declared = {p["name"]: p for p in declaration["parameters"] if p["location"] == location}
        if set(values) - declared.keys():
            raise CustomSearchError("Undeclared OpenAPI parameter")
        for name, param in declared.items():
            if name not in values:
                if param.get("required"):
                    raise CustomSearchError("Missing required OpenAPI parameter")
                continue
            validate(values[name], param["schema"], "parameter")
            pairs = serialize_parameter(param, values[name])
            if location == "query":
                params.extend(pairs)
            elif location == "path":
                path = path.replace("{" + name + "}", quote(pairs[0][1], safe=""))
            elif location == "header":
                headers.update(pairs)
            else:
                cookies.extend(pairs)
    if "{" in path or "}" in path:
        raise CustomSearchError("Missing OpenAPI path parameter")
    auth = operation["auth"]
    if auth["location"] != "none":
        if not isinstance(api_key, str) or not api_key or any(ord(c) < 32 or ord(c) == 127 for c in api_key):
            raise CustomSearchError("Missing search authentication")
        target = auth["location"]
        if target == "header":
            if any(key.lower() == auth["name"].lower() for key in headers):
                raise CustomSearchError("Duplicate authentication parameter")
            headers[auth["name"]] = api_key
        elif target == "query":
            if any(key == auth["name"] for key, _ in params):
                raise CustomSearchError("Duplicate authentication parameter")
            params.append((auth["name"], api_key))
        elif target == "cookie":
            cookies.append((auth["name"], api_key))
        else:
            raise CustomSearchError("Invalid search authentication")
    if cookies:
        headers["Cookie"] = "; ".join(f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in cookies)
    if any(
        key.lower() in TRANSPORT_HEADERS
        or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        for key, value in headers.items()
    ):
        raise CustomSearchError("Invalid OpenAPI header")
    bodies = declaration.get("request_body", {}).get("content", {})
    media = operation.get("media_type", "")
    content = b""
    if bodies:
        if media not in bodies:
            raise CustomSearchError("Invalid OpenAPI request media type")
        if "body" not in request and declaration["request_body"].get("required"):
            raise CustomSearchError("Missing OpenAPI request body")
        if "body" in request:
            body = request["body"]
            validate(body, bodies[media].get("schema", {}), "request body")
            if media == "application/json" or media.endswith("+json"):
                content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            elif media in {"application/x-www-form-urlencoded", "multipart/form-data"}:
                if not isinstance(body, dict):
                    raise CustomSearchError("Invalid OpenAPI form body")
                import httpx

                if media == "multipart/form-data":
                    encoded = httpx.Request(
                        "POST",
                        "https://encoding.invalid",
                        files=[
                            (key, (None, _scalar(child)))
                            for key, value in body.items()
                            for child in (value if isinstance(value, list) else [value])
                        ],
                    )
                else:
                    from urllib.parse import urlencode

                    encoded = httpx.Request(
                        "POST",
                        "https://encoding.invalid",
                        content=urlencode(body, doseq=True).encode(),
                        headers={"Content-Type": media},
                    )
                content = encoded.read()
                media = encoded.headers["Content-Type"]
            elif isinstance(body, str):
                content = body.encode()
            else:
                raise CustomSearchError("OpenAPI media type requires a text body")
            headers["Content-Type"] = media
    elif "body" in request:
        raise CustomSearchError("Undeclared OpenAPI request body")
    return {
        "url": operation["server"].rstrip("/") + path,
        "method": operation["method"],
        "params": params,
        "json": {},
        "headers": headers,
        "body_base64": base64.b64encode(content).decode(),
        "response_metadata": True,
    }


def read_openapi_response(raw, operation, secret=None):
    try:
        envelope = json.loads(raw)
        status = envelope["status"]
        media = envelope["content_type"].split(";", 1)[0].strip().lower()
        payload = base64.b64decode(envelope["body"], validate=True)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise CustomSearchError("Response exceeds size limit")
        if not 200 <= status < 300:
            raise CustomSearchError(f"Search service returned HTTP {status}")
        responses = operation["declaration"]["responses"]
        response = responses.get(str(status), responses.get(f"{status // 100}XX", responses.get("default")))
        if response is None:
            raise CustomSearchError("Undeclared OpenAPI response status")
        content = response.get("content", {})
        matched = content.get(media, content.get(media.split("/")[0] + "/*", content.get("*/*")))
        if content and matched is None:
            raise CustomSearchError("OpenAPI response media type does not match schema")
        if media == "application/json" or media.endswith("+json"):
            result = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            _check_depth(result)
        elif media.startswith("text/") or media in {"application/xml", "application/javascript"}:
            result = payload.decode("utf-8")
        elif not payload:
            result = None
        else:
            result = {"content_type": media, "encoding": "base64", "body": base64.b64encode(payload).decode()}
        if (
            matched is not None
            and "schema" in matched
            and (media.startswith("text/") or media == "application/json" or media.endswith("+json"))
        ):
            validate(result, matched["schema"], "response")
        return _redact(result, secret)
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, CustomSearchError):
            raise
        raise CustomSearchError("Invalid OpenAPI search response") from None


def describe_operations(schema):
    """Use the shared loader's resolved operations; do not parse a second document."""
    if not str(schema.version).startswith(("3.0.", "3.1.")):
        raise CustomSearchError("Expected OpenAPI 3.0 or 3.1")
    document = schema.contents
    descriptions = []
    for path, method, operation, parameters in schema.iter_operations():
        if method.upper() not in METHODS:
            continue
        if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#\\"):
            raise CustomSearchError("Invalid OpenAPI operation path")
        params = []
        for param in parameters:
            location = param["in"]
            if location == "body":
                continue
            if location not in {"query", "path", "header", "cookie"}:
                raise CustomSearchError("Invalid OpenAPI parameter location")
            content = param.get("content", {})
            parameter_schema = param.get("schema", next(iter(content.values()), {}).get("schema", {}))
            params.append({**param, "location": location, "schema": parameter_schema})
        security = schema.security_scheme(operation)
        if security is not None:
            kind = security.get("type")
            if kind == "apiKey":
                security = {"location": security.get("in", ""), "name": security.get("name", "")}
            elif kind in {"http", "oauth2", "openIdConnect"}:
                security = {"location": "header", "name": "Authorization"}
            else:
                raise CustomSearchError("Unsupported OpenAPI credential type")
        declarations = {
            "parameters": params,
            "request_body": operation.get("requestBody", {}),
            "responses": operation.get("responses", {}),
            "security": copy.deepcopy(security),
        }
        for server in operation.get("servers", document["paths"][path].get("servers", document.get("servers", []))):
            url = server["url"]
            for name, variable in server.get("variables", {}).items():
                url = url.replace("{" + name + "}", str(variable["default"]))
            if "{" in url:
                raise CustomSearchError("Unresolved OpenAPI server variable")
            bodies = declarations["request_body"].get("content", {})
            media = next(iter(bodies), "")
            descriptions.append(
                {
                    "version": 2,
                    "server": url,
                    "method": method.upper(),
                    "path": path,
                    "parameters": params,
                    "security": security,
                    "declaration": declarations,
                    "media_type": media,
                    "request": request_template(declarations, media),
                }
            )
    if not descriptions or len(descriptions) > 100:
        raise CustomSearchError("Invalid OpenAPI operations")
    return descriptions

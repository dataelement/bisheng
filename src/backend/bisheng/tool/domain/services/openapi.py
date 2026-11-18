"""OpenAPI document loading and operation discovery shared by tool consumers."""

import json

import yaml
from yaml.tokens import AliasToken, AnchorToken

from bisheng.tool.domain.const import AuthMethod, AuthType
from bisheng.utils.bounded_json import check_tree, strict_json


class OpenApiSchema:
    def __init__(self, contents: dict):
        self.parameter_name = None
        self.api_location = None
        self.contents = contents
        self.version = contents["openapi"]
        self.info = contents.get("info", {})
        self.title = self.info.get("title", "")
        self.auth_type = "basic"
        self.auth_method = 0
        self.description = self.info.get("description", "")
        self.default_server = ""
        self.apis = []

    @classmethod
    def from_content(cls, content: str):
        """Load bounded JSON/YAML and resolve local references without network access."""
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Invalid OpenAPI document size")
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(content)):
            raise ValueError("OpenAPI aliases are unsupported")
        document = strict_json(content) if content.lstrip().startswith("{") else yaml.safe_load(content)
        if not isinstance(document, dict):
            raise ValueError("Invalid OpenAPI document")
        check_tree(document)
        count = 0

        def resolve(value, stack=(), depth=0):
            nonlocal count
            count += 1
            if count > 50000 or depth > 32:
                raise ValueError("OpenAPI reference complexity limit")
            if isinstance(value, dict):
                if "$ref" in value:
                    ref = value["$ref"]
                    if len(value) != 1 or not isinstance(ref, str) or not ref.startswith("#/") or ref in stack:
                        raise ValueError("Unsupported OpenAPI reference")
                    target = document
                    for part in ref[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                    return resolve(target, (*stack, ref), depth + 1)
                return {key: resolve(item, stack, depth + 1) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item, stack, depth + 1) for item in value]
            return value

        return cls(resolve(document))

    def parse_server(self) -> str:
        servers = self.contents.get("servers")
        if not servers:
            raise ValueError("OpenAPI schema must have servers")
        self.default_server = servers[0]["url"] if isinstance(servers, list) else servers["url"]
        security_schemes = self.contents.get("components", {}).get("securitySchemes", {})
        scheme = security_schemes.get("ApiKeyAuth", {})
        requirements = self.contents.get("security", [])
        if isinstance(requirements, list) and len(requirements) == 1 and isinstance(requirements[0], dict):
            if len(requirements[0]) == 1:
                scheme = security_schemes.get(next(iter(requirements[0])), scheme)
        auth_type = scheme.get("type")
        self.auth_type = (
            "custom"
            if auth_type == "apiKey"
            else scheme.get("scheme", scheme.get("schema"))
            if auth_type == "http"
            else "basic"
        )
        self.auth_method = 1 if auth_type in ("apiKey", "http") else 0
        self.api_location = scheme.get("in")
        self.parameter_name = scheme.get("name")
        return self.default_server

    def security_scheme(self, operation):
        requirements = operation.get("security", self.contents.get("security", []))
        if not isinstance(requirements, list):
            raise ValueError("Invalid OpenAPI security")
        if not requirements or requirements == [{}]:
            return None
        if len(requirements) != 1 or not isinstance(requirements[0], dict) or len(requirements[0]) != 1:
            raise ValueError("Unsupported OpenAPI security alternatives")
        name = next(iter(requirements[0]))
        scheme = self.contents.get("components", {}).get("securitySchemes", {}).get(name)
        if not isinstance(scheme, dict):
            raise ValueError("Unknown OpenAPI security scheme")
        return scheme

    def iter_operations(self):
        paths = self.contents.get("paths")
        if not isinstance(paths, dict) or not paths:
            raise ValueError("OpenAPI schema must have paths")
        for path, path_item in paths.items():
            if not isinstance(path, str) or not isinstance(path_item, dict):
                raise ValueError("Invalid OpenAPI path")
            for method, operation in path_item.items():
                if method not in ("get", "post", "put", "delete", "patch", "head", "options", "trace"):
                    continue
                if not isinstance(operation, dict):
                    raise ValueError("Invalid OpenAPI operation")
                merged = {}
                for scope in (path_item.get("parameters", []), operation.get("parameters", [])):
                    if not isinstance(scope, list):
                        raise ValueError("Invalid OpenAPI parameters")
                    seen = set()
                    for param in scope:
                        if not isinstance(param, dict):
                            raise ValueError("Invalid OpenAPI parameter")
                        key = (param.get("in"), param.get("name"))
                        if not all(isinstance(v, str) and v for v in key) or key in seen:
                            raise ValueError("Invalid or duplicate OpenAPI parameter")
                        seen.add(key)
                        merged[key] = param
                parameters = list(merged.values())
                if "requestBody" in operation:
                    content = operation["requestBody"]["content"]
                    if not isinstance(content, dict):
                        raise ValueError("Invalid OpenAPI body")
                    # Preserve the tool editor's supported body media types.
                    for media in content.values():
                        schema = media["schema"]
                        required = schema.get("required", [])
                        props = schema.get("properties", {})
                        if (
                            not isinstance(required, list)
                            or not isinstance(props, dict)
                            or not set(required).issubset(props)
                        ):
                            raise ValueError("Invalid OpenAPI body properties")
                        for name, prop in props.items():
                            parameters.append(
                                {
                                    "name": name,
                                    "in": "body",
                                    "required": name in required,
                                    "description": prop.get("description", ""),
                                    "schema": {**prop, "title": prop.get("title", name)},
                                }
                            )
                yield path, method, operation, parameters

    def parse_paths(self) -> list[dict]:
        self.apis = [
            {
                "path": path,
                "method": method,
                "description": operation.get("description", "") or operation.get("summary", ""),
                "operationId": operation["operationId"],
                "parameters": parameters,
            }
            for path, method, operation, parameters in self.iter_operations()
            if method in ("get", "post", "put", "delete")
        ]
        return self.apis

    @staticmethod
    def parse_openapi_tool_params(
        name: str,
        description: str,
        extra: str | dict,
        server_host: str,
        auth_method: int,
        auth_type: str | None = None,
        api_key: str | None = None,
    ):
        if isinstance(extra, str):
            extra = json.loads(extra)
        # Stitching request header
        headers = {}
        if auth_method == AuthMethod.API_KEY.value:
            if auth_type == AuthType.CUSTOM.value:
                location = extra["api_location"]
                parameter_name = extra["parameter_name"]
                if location == "header":
                    headers = {parameter_name: api_key}
            elif auth_type == AuthType.BASIC.value:
                headers = {"Authorization": f"Basic {api_key}"}
            elif auth_type == AuthType.BEARER.value:
                headers = {"Authorization": f"Bearer {api_key}"}

        # Back to initialization openapiRequired input parameters
        params = {
            "params": extra,
            "headers": headers,
            "api_key": api_key,
            "url": server_host,
            "description": name + description if description else name,
        }
        return params

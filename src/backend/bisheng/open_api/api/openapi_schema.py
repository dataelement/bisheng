"""OpenAPI customization for the key-authenticated v2 surface."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

BEARER_SCHEME_NAME = "OpenApiBearer"


def install_open_api_schema(app: FastAPI) -> None:
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        security_schemes[BEARER_SCHEME_NAME] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "bs-sak-* or bs-pat-*",
        }
        _publish_chat_completion_request(schema)
        for path, path_item in schema.get("paths", {}).items():
            if not path.startswith("/api/v2"):
                continue
            for method, operation in path_item.items():
                if method.lower() in {"get", "put", "post", "delete", "patch", "options", "head"}:
                    operation["security"] = [{BEARER_SCHEME_NAME: []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


CHAT_COMPLETIONS_PATH = "/api/v2/workstation/chat/completions"


def _publish_chat_completion_request(schema: dict) -> None:
    """F073: document both request bodies of the shared chat endpoint.

    The endpoint takes a raw body so it can dispatch on ``run_mode``; without
    this the published contract would show an untyped object. Daily mode stays
    the default branch (``run_mode`` omitted or ``"daily"``); task mode is
    ``run_mode="task"``.
    """
    from bisheng.open_api.domain.schemas.task_mode import OpenTaskSubmitReq
    from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq

    operation = schema.get("paths", {}).get(CHAT_COMPLETIONS_PATH, {}).get("post")
    if operation is None:
        return
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    refs = []
    for model in (OpenDailyChatCompletionReq, OpenTaskSubmitReq):
        model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, definition in model_schema.pop("$defs", {}).items():
            components.setdefault(name, definition)
        components[model.__name__] = model_schema
        refs.append({"$ref": f"#/components/schemas/{model.__name__}"})
    operation["requestBody"] = {
        "required": True,
        "content": {"application/json": {"schema": {"oneOf": refs}}},
    }

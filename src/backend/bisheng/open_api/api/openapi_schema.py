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
        for path, path_item in schema.get("paths", {}).items():
            if not path.startswith("/api/v2"):
                continue
            for method, operation in path_item.items():
                if method.lower() in {"get", "put", "post", "delete", "patch", "options", "head"}:
                    operation["security"] = [{BEARER_SCHEME_NAME: []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


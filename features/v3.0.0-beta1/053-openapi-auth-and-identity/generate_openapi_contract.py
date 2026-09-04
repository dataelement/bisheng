"""Generate the customer-facing API-key OpenAPI contract from the live app."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "src" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
app = importlib.import_module("bisheng.main").app

OUTPUT = Path(__file__).with_name("openapi-v2-key-auth-api.json")


def _schema_references(value: object) -> set[str]:
    if isinstance(value, dict):
        references = {
            item["$ref"].removeprefix("#/components/schemas/")
            for item in [value]
            if isinstance(item.get("$ref"), str)
            and item["$ref"].startswith("#/components/schemas/")
        }
        for item in value.values():
            references.update(_schema_references(item))
        return references
    if isinstance(value, list):
        references: set[str] = set()
        for item in value:
            references.update(_schema_references(item))
        return references
    return set()


def generate() -> dict:
    source = app.openapi()
    paths = {path: value for path, value in source["paths"].items() if path.startswith("/api/v2/")}
    source_schemas = source.get("components", {}).get("schemas", {})
    required = _schema_references(paths)
    schemas: dict[str, object] = {}
    while required:
        name = required.pop()
        if name in schemas or name not in source_schemas:
            continue
        schemas[name] = source_schemas[name]
        required.update(_schema_references(source_schemas[name]))
    return {
        "openapi": source.get("openapi", "3.1.0"),
        "info": {
            "title": "BiSheng API-key API",
            "version": "2.0",
            "description": "HTTP and WebSocket endpoints authenticated with a Bearer API key.",
        },
        "paths": paths,
        "components": {
            "schemas": dict(sorted(schemas.items())),
            "securitySchemes": {
                "OpenApiBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "API Key"}
            },
        },
        "x-websocket-endpoints": [
            {
                "url": "/api/v2/workflow/chat/{workflow_id}",
                "authorization": "Bearer API Key",
                "headers": ["Authorization", "X-End-User", "X-On-Behalf-Of"],
                "query": ["chat_id"],
            },
            {
                "url": "/api/v2/assistant/chat/{assistant_id}",
                "authorization": "Bearer API Key",
                "headers": ["Authorization", "X-End-User", "X-On-Behalf-Of"],
                "query": ["chat_id"],
            },
        ],
    }


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(generate(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

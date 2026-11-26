"""Schema-driven request construction and complete responses; management regression."""

import base64
import copy
import json
from uuid import UUID

import pytest
import yaml
from fastapi import HTTPException

from bisheng.tool.domain.services import web_search as service
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng_langchain.gpts.tools.web_search.custom import CustomSearchError, build_request
from bisheng_langchain.gpts.tools.web_search.openapi_request import describe_operations, read_openapi_response
from bisheng_langchain.gpts.tools.web_search.tool import CustomSearch
from test.tool.test_custom_web_search import store  # noqa: F401 -- shared isolated database fixture


def document(body=None, media="application/json", output=None):
    operation = {"operationId": "search", "responses": {"201": {"content": {media: {"schema": output or {}}}}}}
    if body is not None:
        operation["requestBody"] = {"required": True, "content": {media: {"schema": body}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Search", "version": "1"},
        "servers": [{"url": "https://example.com"}],
        "paths": {"/search": {"post": operation}},
    }


def draft(doc):
    item = describe_operations(OpenApiSchema.from_content(json.dumps(doc)))[0]
    return {
        "operation": {
            "version": 2,
            "server": item["server"],
            "method": item["method"],
            "path": item["path"],
            "declaration": item["declaration"],
            "media_type": item["media_type"],
            "request": item["request"],
            "auth": item["security"] or {"location": "none", "name": ""},
            "response_mode": "raw",
        },
        "mapping": {},
    }


def response(value, status=201, media="application/json"):
    payload = json.dumps(value).encode() if media.endswith("json") else value.encode()
    return json.dumps({"status": status, "content_type": media, "body": base64.b64encode(payload).decode()}).encode()


@pytest.mark.parametrize("auth", [{"location": "none", "name": ""}, {"location": "header", "name": "Other-Key"}])
def test_authentication_still_matches_declaration_without_proof(auth):
    config = draft(document())
    config["operation"]["declaration"]["security"] = {"location": "header", "name": "X-Key"}
    config["operation"]["auth"] = auth
    with pytest.raises(HTTPException, match="authentication settings"):
        service._custom(config)


@pytest.mark.parametrize("old_proof", [None, {"key_id": "root-key", "ciphertext": "expired-root-proof"}, "invalid"])
@pytest.mark.usefixtures("store")
async def test_copied_settings_preview_save_and_executor_ignore_old_proof(monkeypatch, old_proof):
    """Copied declarations work in their target tenant without re-importing a schema."""
    from unittest.mock import Mock

    from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
    from bisheng.tool.domain.services import executor

    config = draft(document())
    if old_proof is not None:
        config["proof"] = old_proof
    raw = json.dumps({"enabled": True, "type": "custom", "config": {"custom": config}})
    category = GptsToolsType(id=17, name="copied search", tenant_id=2, is_preset=1, extra=raw)
    tool = GptsTools(id=39, name="search", type=17, tool_key="web_search", tenant_id=2, is_preset=1)
    async with service.get_async_db_session() as db:
        db.add(category)
        db.add(tool)
        await db.commit()

    monkeypatch.setattr(service, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(executor, "get_current_tenant_id", lambda: 2)
    view = await service.get_settings(17)
    expected = {key: config[key] for key in ("operation", "mapping")}
    assert view["providers"]["custom"] == expected

    upstream = Mock(return_value=response({"answer": "found"}))
    monkeypatch.setattr(service, "execute_request", upstream)
    preview = await service.search_preview(17, {"draft": config, "query": "query", "secret": {"action": "keep"}})
    assert preview["results"] == {"answer": "found"}
    upstream.assert_called_once()

    loaded = object()
    loader = Mock(return_value=[loaded])
    monkeypatch.setattr(executor, "load_tools", loader)
    assert executor.ToolExecutor._init_preset_tool(tool, category) is loaded
    assert loader.call_args.kwargs["tool_params"]["web_search"]["config"]["custom"] == expected
    assert category.extra == raw

    saved = await service.put_settings(
        17,
        service.SettingsWrite(
            revision=view["revision"],
            enabled=True,
            type="custom",
            prompt="",
            providers={"custom": config},
            custom_secret={"action": "keep"},
        ),
        42,
    )
    assert saved["providers"]["custom"] == expected
    async with service.get_async_db_session() as db:
        persisted = await db.get(GptsToolsType, 17)
        assert json.loads(persisted.extra)["config"]["custom"] == expected

    monkeypatch.setattr(service, "get_current_tenant_id", lambda: 1)
    with pytest.raises(HTTPException) as exc:
        await service.get_settings(17)
    assert exc.value.status_code == 404


@pytest.mark.usefixtures("store")
async def test_responses_web_search_schema_import_and_request():
    content = """
openapi: 3.0.3
info:
  title: openai_web_search
  version: 1.0.0
  description: Search the web and answer
servers:
  - url: https://search.example/modelapi
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
security:
  - BearerAuth: []
paths:
  /v1/responses:
    post:
      operationId: openai_web_search
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [model, input, tools]
              properties:
                model:
                  type: string
                input:
                  type: string
                tools:
                  type: array
                  minItems: 1
                  items:
                    type: object
                    required: [type]
                    properties:
                      type:
                        type: string
                        enum: [web_search]
      responses:
        "200":
          description: Answer and sources
          content:
            application/json:
              schema:
                type: object
                additionalProperties: true
"""
    imported = (await service.schema_preview(16, {"content": content}))["operations"][0]
    op = draft(yaml.safe_load(content))["operation"]
    op["request"]["body"].update(model="fixture-model", input="{{query}}")
    assert "proof" not in imported
    service._custom({"operation": op, "mapping": {}})
    request = build_request(op, 'search "quoted" text', "Bearer fixture-token")
    assert request["url"] == "https://search.example/modelapi/v1/responses"
    assert request["headers"]["Authorization"] == "Bearer fixture-token"
    assert json.loads(base64.b64decode(request["body_base64"])) == {
        "model": "fixture-model",
        "input": 'search "quoted" text',
        "tools": [{"type": "web_search"}],
    }
    output = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Answer"}]}]}
    assert read_openapi_response(response(output, status=200), op) == output


def nested_document():
    return document(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "model", "commands"],
            "properties": {
                "id": {"type": "string"},
                "model": {"type": "string"},
                "commands": {
                    "type": "object",
                    "required": ["search_query"],
                    "properties": {
                        "search_query": {
                            "type": "array",
                            "minItems": 2,
                            "items": {
                                "type": "object",
                                "required": ["q"],
                                "properties": {
                                    "q": {"type": "string"},
                                    "options": {"type": "object", "additionalProperties": {"type": "boolean"}},
                                },
                            },
                        }
                    },
                },
            },
        }
    )


def test_nested_arrays_dynamic_query_and_uuid_preserve_values():
    op = draft(nested_document())["operation"]
    op["request"]["body"] = {
        "id": "{{uuid}}",
        "model": "configured-model",
        "commands": {"search_query": [{"q": "{{query}}", "options": {"fresh": True}}, {"q": "second query"}]},
    }
    query = 'a "quoted" search \\ with {{uuid}} and 中文'
    bodies = [json.loads(base64.b64decode(build_request(op, query)["body_base64"])) for _ in range(2)]
    assert bodies[0]["commands"]["search_query"][0] == {"q": query, "options": {"fresh": True}}
    assert bodies[0]["model"] == "configured-model"
    assert str(UUID(bodies[0]["id"])) == bodies[0]["id"]
    assert bodies[0]["id"] != bodies[1]["id"]
    broken = copy.deepcopy(op)
    broken["request"]["body"]["commands"]["search_query"] = [{}]
    with pytest.raises(CustomSearchError, match="does not match schema"):
        build_request(broken, query)


def test_root_array_union_null_and_complete_responses():
    op = draft(
        document(
            {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "integer"},
                        {"type": "null"},
                        {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}},
                    ]
                },
            }
        )
    )["operation"]
    op["request"]["body"] = [3, None, {"q": "{{query}}"}]
    assert json.loads(base64.b64decode(build_request(op, "keyword")["body_base64"])) == [3, None, {"q": "keyword"}]
    for value in ({"payload": {"extra": [True, 5]}}, [1, "two", None], 3, "plain", None):
        assert read_openapi_response(response(value), op) == value


def test_locations_styles_and_path_encoding():
    doc = document()
    operation = doc["paths"].pop("/search")["post"]
    operation["parameters"] = [
        {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "tags", "in": "query", "schema": {"type": "array", "items": {"type": "string"}}},
        {
            "name": "filters",
            "in": "query",
            "style": "deepObject",
            "explode": True,
            "schema": {"type": "object", "properties": {"recent": {"type": "boolean"}}},
        },
        {"name": "X-Region", "in": "header", "schema": {"type": "string"}},
    ]
    doc["paths"]["/search/{name}"] = {"patch": operation}
    op = draft(doc)["operation"]
    op["request"] = {
        "path": {"name": "a/b?c"},
        "query": {"tags": ["x", "y"], "filters": {"recent": True}},
        "header": {"X-Region": "cn"},
    }
    req = build_request(op, "unused")
    assert req["url"].endswith("/search/a%2Fb%3Fc") and req["method"] == "PATCH"
    assert req["params"] == [("tags", "x"), ("tags", "y"), ("filters[recent]", "true")]
    assert req["headers"]["X-Region"] == "cn"
    op["request"]["header"]["Host"] = "other.invalid"
    with pytest.raises(CustomSearchError, match="Undeclared"):
        build_request(op, "unused")


@pytest.mark.parametrize("media", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_declared_non_json_request_body(media):
    schema = (
        {"type": "string"}
        if media == "text/plain"
        else {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    )
    op = draft(document(schema, media=media))["operation"]
    op["request"]["body"] = "{{query}}" if media == "text/plain" else {"q": "{{query}}"}
    req = build_request(op, "hello")
    assert b"hello" in base64.b64decode(req["body_base64"])
    assert req["headers"]["Content-Type"].startswith(media)


def test_response_schema_status_and_redaction():
    op = draft(
        document(output={"type": "object", "required": ["output"], "properties": {"output": {"type": "string"}}})
    )["operation"]
    assert read_openapi_response(response({"output": "secret-value"}), op, "secret-value") == {"output": "[REDACTED]"}
    with pytest.raises(CustomSearchError, match="does not match schema"):
        read_openapi_response(response({"output": 3}), op)
    with pytest.raises(CustomSearchError, match="HTTP 403"):
        read_openapi_response(response({"error": "do not expose"}, 403), op)
    with pytest.raises(CustomSearchError, match="Undeclared"):
        read_openapi_response(response({}, 202), op)
    text = draft(document(media="text/plain", output={"type": "string"}))["operation"]
    assert read_openapi_response(response("complete text", media="text/plain"), text) == "complete text"


@pytest.mark.usefixtures("store")
async def test_real_save_read_preview_runtime_without_proof(monkeypatch):
    """AC-14/15/17/18/21/22/24/26/27/28: actual management and tool with isolated upstream."""
    doc = nested_document()
    doc["components"] = {"securitySchemes": {"key": {"type": "apiKey", "in": "header"}}}
    doc["security"] = [{"key": []}]
    item = (await service.schema_preview(16, {"content": json.dumps(doc)}))["operations"][0]
    config = draft(doc)
    assert "proof" not in item
    config["operation"]["request"]["body"] = {
        "id": "{{uuid}}",
        "model": "configured-model",
        "commands": {"search_query": [{"q": "{{query}}"}, {"q": "extra"}]},
    }
    with pytest.raises(HTTPException, match="authentication"):
        service._custom(config)
    config["operation"]["auth"]["name"] = "Authorization"
    current = await service.get_settings(16)
    saved = await service.put_settings(
        16,
        service.SettingsWrite(
            revision=current["revision"],
            enabled=True,
            type="custom",
            prompt="",
            providers={"custom": config},
            custom_secret={"action": "replace", "value": "Bearer synthetic-search-secret"},
        ),
        42,
    )
    restored = await service.get_settings(16)
    assert saved["custom_secret_configured"] and restored["providers"]["custom"] == config
    assert "Bearer synthetic-search-secret" not in json.dumps(restored)
    calls = []
    value = {"answer": "arbitrary output", "payload": {"scores": [1, None, 3]}, "extra": True}

    def upstream(req):
        calls.append(req)
        assert req["headers"]["Authorization"] == "Bearer synthetic-search-secret"
        return response(value)

    monkeypatch.setattr(service, "execute_request", upstream)
    tested = await service.search_preview(16, {"draft": config, "query": "actual query", "secret": {"action": "keep"}})
    assert tested["preview"] == tested["results"] == value
    from bisheng_langchain.gpts.tools.web_search import custom

    monkeypatch.setattr(custom, "execute_request", upstream)
    runtime = CustomSearch(operation=config["operation"], mapping={}, api_key="Bearer synthetic-search-secret")
    assert json.loads(runtime.invoke("actual query")) == value
    bodies = [json.loads(base64.b64decode(req["body_base64"])) for req in calls]
    assert bodies[0]["commands"]["search_query"][0]["q"] == "actual query" and bodies[0]["id"] != bodies[1]["id"]
    invalid = copy.deepcopy(config)
    invalid["operation"]["request"]["body"]["commands"]["search_query"] = "wrong-type"
    with pytest.raises(HTTPException, match="does not match schema"):
        service._custom(invalid)


@pytest.mark.parametrize("response_delay", [0, 6])
def test_nested_post_uses_real_isolated_http_transport(monkeypatch, response_delay):
    """AC-15/18/26: inspect bytes received by a real HTTP server, not a request mock."""
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from bisheng_langchain.gpts.tools.web_search import custom

    received = []
    expected = {"output": "full text", "arbitrary": {"values": [2, False, None]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            import time

            time.sleep(response_delay)
            payload = json.dumps(expected).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        doc = nested_document()
        doc["servers"][0]["url"] = f"http://127.0.0.1:{server.server_port}"
        op = draft(doc)["operation"]
        op["request"]["body"] = {
            "id": "{{uuid}}",
            "model": "configured-model",
            "commands": {"search_query": [{"q": "{{query}}"}, {"q": "second"}]},
        }
        monkeypatch.setenv("BS_CUSTOM_SEARCH_ORIGINS", doc["servers"][0]["url"])
        monkeypatch.setenv("BS_CUSTOM_SEARCH_PORTS", str(server.server_port))
        monkeypatch.setenv("BS_CUSTOM_SEARCH_PRIVATE_CIDRS", "")
        worker = custom._run_worker
        code = 'import importlib.util,sys; s=importlib.util.spec_from_file_location("transport",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.allowed=lambda address,private: address == "127.0.0.1"; m.main()'
        monkeypatch.setattr(
            custom,
            "_run_worker",
            lambda payload, command: worker(payload, [sys.executable, "-I", "-c", code, command[-1]]),
        )
        tool = CustomSearch(operation=op, mapping={})
        assert json.loads(tool.invoke("actual search")) == expected
        assert received[0]["commands"]["search_query"] == [{"q": "actual search"}, {"q": "second"}]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

"""Custom search: import, settings, preview, execution and essential access checks."""

import json
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.permission.application import identity
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.api.tool import router
from bisheng.tool.domain.models.gpts_tools import (
    GptsTools,
    GptsToolsDao,
    GptsToolsType,
    GptsToolsTypeRead,
    WebSearchSecret,
)
from bisheng.tool.domain.services import executor
from bisheng.tool.domain.services import web_search as search_service
from bisheng.tool.domain.services.executor import ToolExecutor, ToolInitializationError
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng.tool.domain.services.tool import ToolServices
from bisheng_langchain.gpts.tools.web_search import custom
from bisheng_langchain.gpts.tools.web_search.custom import (
    CustomSearchError,
    build_request,
    map_response,
)


@pytest.fixture(autouse=True)
def no_search_key_environment(monkeypatch):
    monkeypatch.delenv("BISHENG_WEB_SEARCH_SECRET_KEYRING", raising=False)
    monkeypatch.delenv("BISHENG_WEB_SEARCH_SECRET_ACTIVE_KEY_ID", raising=False)


def test_system_cipher_uses_platform_encrypt_token_without_keyring():
    cipher = search_service.WebSearchCipher.configured()
    key_id, token = cipher.encrypt("private-value", tenant_id=1, category_id=16)
    assert key_id == "platform"
    assert cipher.decrypt(key_id, token, tenant_id=1, category_id=16) == "private-value"
    with pytest.raises(search_service.SecretUnavailable):
        cipher.decrypt(key_id, token, tenant_id=2, category_id=16)
    with pytest.raises(search_service.SecretUnavailable):
        cipher.decrypt("old", token, tenant_id=1, category_id=16)


@pytest.fixture
async def store(monkeypatch, request):
    tenant_id = getattr(request, "param", 1)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for model in (GptsToolsType, GptsTools, WebSearchSecret):
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(search_service, "get_async_db_session", session)
    monkeypatch.setattr(search_service, "get_current_tenant_id", lambda: tenant_id)
    async with session() as db:
        db.add(GptsToolsType(id=16, name="search", tenant_id=tenant_id, is_preset=1, extra="{}"))
        db.add(GptsTools(id=38, name="search", type=16, tool_key="web_search", tenant_id=tenant_id, is_preset=1))
        await db.commit()
    yield session
    await engine.dispose()


def draft(revision, action):
    return search_service.SettingsWrite(
        revision=revision,
        enabled=True,
        type="custom",
        prompt="",
        providers={
            "custom": {
                "operation": {
                    "server": "https://example.com",
                    "method": "GET",
                    "path": "/search",
                    "query_parameter": {"location": "query", "name": "q"},
                    "fixed_params": [],
                    "auth": {"location": "header", "name": "X-Key"},
                },
                "mapping": {
                    "results": "results",
                    "title": "title",
                    "url": "url",
                    "snippet": "snippet",
                    "source": "",
                    "siteIcon": "",
                    "datePublished": "",
                },
            }
        },
        custom_secret=action,
    )


@pytest.mark.parametrize("method,location", [("get", "query"), ("post", "body")])
async def test_shared_openapi_import_for_custom_tool_and_search(store, method, location):
    operation = {"operationId": "search", "responses": {"200": {"content": {"application/json": {}}}}}
    if location == "query":
        operation["parameters"] = [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}]
    else:
        operation["requestBody"] = {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    }
                }
            }
        }
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Search", "version": "1.0"},
        "servers": [{"url": "https://example.com"}],
        "paths": {"/search": {method: operation}},
    }
    content = json.dumps(document) if method == "get" else yaml.safe_dump(document)
    platform_tool = await ToolServices.parse_openapi_schema(None, content)
    imported = (await search_service.schema_preview(16, {"content": content}))["operations"][0]
    parameter = platform_tool.children[0].api_params[0]
    assert (platform_tool.server_host, parameter["name"], parameter["in"], parameter["schema"]["type"]) == (
        imported["server"],
        "q",
        location,
        "string",
    )
    assert (imported["server"], imported["method"], imported["path"]) == (
        "https://example.com",
        method.upper(),
        "/search",
    )
    assert imported["version"] == 2
    if method == "get":
        assert imported["parameters"][0]["schema"] == {"type": "string"}
    else:
        assert (
            imported["declaration"]["request_body"]["content"]["application/json"]["schema"]
            == operation["requestBody"]["content"]["application/json"]["schema"]
        )
    if method == "post":
        operation["requestBody"]["content"]["application/json"]["schema"]["properties"]["options"] = {
            "type": "object",
            "properties": {"language": {"type": "string"}},
        }
        nested = await ToolServices.parse_openapi_schema(None, json.dumps(document))
        assert nested.children[0].api_params[1]["schema"]["properties"] == {"language": {"type": "string"}}
        nested_import = (await search_service.schema_preview(16, {"content": json.dumps(document)}))["operations"][0]
        assert (
            nested_import["declaration"]["request_body"]["content"]["application/json"]["schema"]["properties"][
                "options"
            ]["type"]
            == "object"
        )
    operation["parameters"] = [{"name": "q", "in": "query", "schema": {"$ref": "https://other.example/schema"}}]
    with pytest.raises(ValueError):
        OpenApiSchema.from_content(json.dumps(document))


async def test_roundtrip_replace_keep_clear_and_stale_revision(store):
    first = await search_service.get_settings(16)
    saved = await search_service.put_settings(
        16, draft(first["revision"], {"action": "replace", "value": "secret-value"}), 42
    )
    assert saved["custom_secret_configured"] is True
    assert "secret-value" not in json.dumps(saved)
    async with store() as db:
        secret = (await db.exec(search_service.select(WebSearchSecret))).one()
        assert "secret-value" not in secret.ciphertext
        assert secret.updated_by == 42
        category = (await db.exec(search_service.select(GptsToolsType))).one()
        assert "secret-value" not in category.extra
    with pytest.raises(HTTPException) as exc:
        await search_service.put_settings(16, draft(first["revision"], {"action": "keep"}), 42)
    assert exc.value.status_code == 409
    invalid = draft(saved["revision"], {"action": "keep"})
    invalid.providers["custom"]["operation"]["path"] = "invalid-path"
    with pytest.raises(HTTPException) as exc:
        await search_service.put_settings(16, invalid, 42)
    assert exc.value.status_code == 422
    kept = await search_service.put_settings(16, draft(saved["revision"], {"action": "keep"}), 42)
    assert kept["custom_secret_configured"]
    req = draft(kept["revision"], {"action": "clear"})
    req.type = "bing"
    cleared = await search_service.put_settings(16, req, 42)
    assert not cleared["custom_secret_configured"]


async def test_settings_filters_and_preserves_unknown_data(store):
    legacy = {
        "bing": {
            "api_key": "bing-secret",
            "base_url": "https://example.com",
            "unknown": [{"api_key": "hidden-list-secret"}],
        },
        "legacy": {"token": "hidden-provider-secret"},
    }
    async with store() as db:
        category = (await db.exec(search_service.select(GptsToolsType))).one()
        category.extra = json.dumps({"config": legacy})
        db.add(category)
        await db.commit()
    view = await search_service.get_settings(16)
    assert view["providers"] == {"bing": {"api_key": "********", "base_url": "https://example.com"}}
    req = search_service.SettingsWrite(
        revision=view["revision"],
        enabled=True,
        type="bing",
        prompt="",
        providers=view["providers"],
        custom_secret={"action": "keep"},
    )
    saved = await search_service.put_settings(16, req, 42)
    assert saved["providers"] == view["providers"]
    async with store() as db:
        category = (await db.exec(search_service.select(GptsToolsType))).one()
        assert json.loads(category.extra)["config"] == legacy
    req.revision = saved["revision"]
    req.providers["bing"]["new-field"] = "secret"
    with pytest.raises(HTTPException) as exc:
        await search_service.put_settings(16, req, 42)
    assert exc.value.status_code == 422


async def test_rejects_child_override_and_cross_tenant(store, monkeypatch):
    first = await search_service.get_settings(16)
    async with store() as db:
        child = (await db.exec(search_service.select(GptsTools))).one()
        child.extra = '{"type":"bing"}'
        db.add(child)
        await db.commit()
    changed = await search_service.get_settings(16)
    with pytest.raises(HTTPException) as exc:
        await search_service.put_settings(
            16, draft(changed["revision"], {"action": "replace", "value": "secret-value"}), 42
        )
    assert exc.value.status_code == 409
    assert first["revision"] != changed["revision"]
    monkeypatch.setattr(search_service, "get_current_tenant_id", lambda: 2)
    with pytest.raises(HTTPException) as exc:
        await search_service.get_settings(16)
    assert exc.value.status_code == 404


async def test_preview_redacts_and_does_not_persist(store, monkeypatch):

    monkeypatch.setattr(search_service, "get_async_db_session", store)
    monkeypatch.setattr(search_service, "get_current_tenant_id", lambda: 1)
    first = await search_service.get_settings(16)
    req = draft(first["revision"], {"action": "replace", "value": "secret-value"})
    saved = await search_service.put_settings(16, req, 42)
    monkeypatch.setattr(
        search_service,
        "execute_request",
        lambda request: b'{"results":[{"title":"secret-value","url":"https://example.com","snippet":"text"}]}',
    )
    result = await search_service.search_preview(
        16, {"draft": req.providers["custom"], "query": "q", "secret": {"action": "keep"}}
    )
    assert "secret-value" not in json.dumps(result)
    assert len(result["results"]) == 1
    assert (await search_service.get_settings(16))["revision"] == saved["revision"]


@pytest.mark.parametrize("search_category", [True, False])
async def test_generic_search_view_omits_custom_even_without_auth(store, monkeypatch, search_category):
    first = await search_service.get_settings(16)
    req = draft(first["revision"], {"action": "keep"})
    operation = req.providers["custom"]["operation"]
    operation["auth"] = {"location": "none", "name": ""}
    operation["fixed_params"] = [
        {"location": "query", "name": "key", "value": "private-fixed-value"},
        {"location": "query", "name": "credential", "value": "another-fixed-value"},
    ]
    admin = await search_service.put_settings(16, req, 42)
    assert admin["providers"]["custom"]["operation"]["fixed_params"] == operation["fixed_params"]
    original = json.dumps({"config": {"custom": {"fixed_params": operation["fixed_params"]}}})
    async with store() as db:
        category = (await db.exec(search_service.select(GptsToolsType))).one()
        child = (await db.exec(search_service.select(GptsTools))).one()
        child.extra = original
        await db.commit()
    monkeypatch.setattr("bisheng.tool.domain.models.gpts_tools.get_async_db_session", store)
    loaded_children = await GptsToolsDao.aget_list_by_type([category.id])
    view = GptsToolsTypeRead(**category.model_dump(), children=loaded_children)
    view.mask_sensitive_data(search_category=search_category)
    assert "custom" not in json.loads(view.children[0].extra)["config"]
    if search_category:
        assert "custom" not in json.loads(view.extra)["config"]
        generic = json.dumps(view.model_dump(), default=str)
        assert "private-fixed-value" not in generic
        assert "another-fixed-value" not in generic
    assert loaded_children[0].extra == original


async def test_secret_cannot_be_saved_in_plaintext_settings(store):
    initial = await search_service.get_settings(16)
    req = draft(initial["revision"], {"action": "replace", "value": "secret-value"})
    req.prompt = "Bearer secret-value"
    with pytest.raises(HTTPException, match="Credentials must not appear"):
        await search_service.put_settings(16, req, 42)
    assert await search_service.get_settings(16) == initial


SETTINGS = {
    "revision": "revision",
    "enabled": True,
    "type": "bing",
    "prompt": "",
    "providers": {},
    "custom_secret": {"action": "keep"},
}


ROUTES = [
    ("GET", "settings", None, search_service, "get_settings"),
    ("PUT", "settings", SETTINGS, search_service, "put_settings"),
    ("POST", "schema", {"content": "{}"}, search_service, "schema_preview"),
    ("POST", "test", {"draft": {}, "query": "hello", "secret": {"action": "keep"}}, search_service, "search_preview"),
]


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def handle_error(request, exc):
        return JSONResponse(status_code=200, content=exc.to_dict())

    return app


@pytest.mark.parametrize("method,path,body,module,service", ROUTES)
@pytest.mark.parametrize(
    "claim,super_admin,admin_tenants,actor_tenant,data_scope,allowed",
    [
        (True, True, (), 68, "all_visible", True),
        (False, False, (68,), 68, "all_visible", True),
        (False, False, (69,), 68, "all_visible", False),
        (False, False, (68,), 69, "all_visible", False),
        (False, False, (), 68, "all_visible", False),
        (True, False, (), 68, "all_visible", False),
        (True, True, (), 68, "personal_only", False),
        (False, False, (68,), 68, "personal_only", False),
    ],
)
async def test_management_requires_current_tenant_administrator(
    app,
    monkeypatch,
    method,
    path,
    body,
    module,
    service,
    claim,
    super_admin,
    admin_tenants,
    actor_tenant,
    data_scope,
    allowed,
):
    user = SimpleNamespace(user_id=42, tenant_id=68, is_global_super=claim)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    actor = PermissionActor(
        user_id=42,
        current_tenant_id=actor_tenant,
        super_admin=super_admin,
        tenant_admin_tenant_ids=frozenset(admin_tenants),
        data_scope=data_scope,
    )
    resolve = AsyncMock(return_value=actor)
    monkeypatch.setattr(identity, "resolve_permission_actor", resolve)
    monkeypatch.setattr(identity, "get_current_tenant_id", lambda: 68)
    call = AsyncMock(return_value={"marker": "authorized"})
    monkeypatch.setattr(module, service, call)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/tool/16/web-search/{path}", json=body)

    assert response.status_code == 200
    resolve.assert_awaited_once_with(user)
    if allowed:
        assert response.json()["data"] == {"marker": "authorized"}
        call.assert_awaited_once()
        assert call.await_args.args[0] == 16
    else:
        assert response.json()["status_code"] == 403
        call.assert_not_awaited()


@pytest.mark.parametrize("store", [68], indirect=True)
@pytest.mark.parametrize("super_admin", [False, True])
async def test_api_import_save_read_and_preview_without_proof(app, store, monkeypatch, super_admin):
    """AC-02/06/07/08: exercise actual management handlers and isolated persistence."""
    from test.e2e.helpers.api import assert_resp_200

    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=42, tenant_id=68, is_global_super=super_admin
    )
    monkeypatch.setattr(identity, "get_current_tenant_id", lambda: 68)
    monkeypatch.setattr(
        identity,
        "resolve_permission_actor",
        AsyncMock(
            return_value=PermissionActor(
                user_id=42,
                current_tenant_id=68,
                super_admin=super_admin,
                tenant_admin_tenant_ids=frozenset() if super_admin else frozenset({68}),
            )
        ),
    )
    content = json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "Search", "version": "1"},
            "servers": [{"url": "https://example.com"}],
            "paths": {"/search": {"get": {"responses": {"200": {"content": {"application/json": {}}}}}}},
        }
    )
    upstream = Mock(return_value=b'{"status":200,"content_type":"application/json","body":"e30="}')
    monkeypatch.setattr(search_service, "execute_request", upstream)
    base = "/api/v1/tool/16/web-search"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        imported = assert_resp_200(await client.post(f"{base}/schema", json={"content": content}))["operations"][0]
        assert "proof" not in imported
        config = {
            "operation": {
                key: imported[key]
                for key in ("version", "server", "method", "path", "declaration", "media_type", "request")
            },
            "mapping": {},
        }
        config["operation"].update(auth={"location": "none", "name": ""}, response_mode="raw")
        current = assert_resp_200(await client.get(f"{base}/settings"))
        saved = assert_resp_200(
            await client.put(
                f"{base}/settings",
                json={
                    "revision": current["revision"],
                    "enabled": True,
                    "type": "custom",
                    "prompt": "",
                    "providers": {"custom": config},
                    "custom_secret": {"action": "keep"},
                },
            )
        )
        assert "proof" not in saved["providers"]["custom"]
        restored = assert_resp_200(await client.get(f"{base}/settings"))
        assert restored["providers"]["custom"] == config
        config["proof"] = {"key_id": "root", "ciphertext": "copied-from-root"}
        preview = assert_resp_200(
            await client.post(
                f"{base}/test",
                json={
                    "draft": config,
                    "query": "query",
                    "secret": {"action": "keep"},
                },
            )
        )
        assert preview == {"status": "success", "preview": {}, "results": {}}
        upstream.assert_called_once()


@pytest.mark.parametrize("provider,child_override", [("bing", False), ("searXNG", True)])
def test_legacy_provider_initialization_does_not_use_custom_secrets(monkeypatch, provider, child_override):
    monkeypatch.delenv("BISHENG_WEB_SEARCH_SECRET_KEYRING", raising=False)
    monkeypatch.delenv("BISHENG_WEB_SEARCH_SECRET_ACTIVE_KEY_ID", raising=False)
    secret_session = Mock(side_effect=AssertionError("legacy provider accessed custom secret storage"))
    monkeypatch.setattr("bisheng.core.database.get_sync_db_session", secret_session)
    expected = {"type": provider, "config": {provider: {"api_key": "legacy-key", "base_url": "https://example.com"}}}
    category_extra = json.dumps({"type": "bing"} if child_override else expected)
    tool = GptsTools(
        id=38, name="search", type=16, tool_key="web_search", extra=json.dumps(expected) if child_override else None
    )
    category = GptsToolsType(id=16, name="search", extra=category_extra)
    loaded = object()
    loader = Mock(return_value=[loaded])
    monkeypatch.setattr(executor, "load_tools", loader)

    assert ToolExecutor._init_preset_tool(tool, category) is loaded
    loader.assert_called_once_with(tool_params={"web_search": expected})
    secret_session.assert_not_called()
    assert json.loads(category.extra) == json.loads(category_extra)
    if child_override:
        assert json.loads(tool.extra) == expected


async def test_import_save_executor_http(tmp_path, monkeypatch):
    requests = []
    schema_requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/openapi.json":
                schema_requests.append(self.headers.get("X-Key"))
                data = schema
            else:
                requests.append((self.path, self.headers.get("X-Key")))
                data = {"results": [{"title": "Found", "url": "https://example.org/item", "snippet": "Text"}]}
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    origin = f"http://127.0.0.1:{port}"
    database = tmp_path / "search.sqlite"
    sync_engine = create_engine(f"sqlite:///{database}")
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    try:
        for model in (GptsToolsType, GptsTools, WebSearchSecret):
            model.__table__.create(sync_engine)
        with Session(sync_engine) as db:
            db.add(GptsToolsType(id=16, name="search", tenant_id=1, is_preset=1, extra="{}"))
            db.add(GptsTools(id=38, name="search", type=16, tool_key="web_search", tenant_id=1, is_preset=1))
            db.commit()

        @asynccontextmanager
        async def async_session():
            async with AsyncSession(async_engine, expire_on_commit=False) as db:
                yield db

        @contextmanager
        def sync_session():
            with Session(sync_engine) as db:
                yield db

        async def get_tool(*, tool_id):
            async with async_session() as db:
                return await db.get(GptsTools, tool_id)

        async def get_type(*, tool_type_id):
            async with async_session() as db:
                return await db.get(GptsToolsType, tool_type_id)

        monkeypatch.setattr(search_service, "get_async_db_session", async_session)
        monkeypatch.setattr(search_service, "get_current_tenant_id", lambda: 1)
        monkeypatch.setattr("bisheng.core.database.get_sync_db_session", sync_session)
        monkeypatch.setattr(GptsToolsDao, "aget_one_tool", get_tool)
        monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", get_type)
        monkeypatch.setattr(executor, "get_current_tenant_id", lambda: 1)
        monkeypatch.setattr("bisheng.utils.http_middleware._check_is_global_super", AsyncMock(return_value=False))
        monkeypatch.setattr(executor, "check_business_action", AsyncMock(return_value=True))
        monkeypatch.setattr(executor.telemetry_service, "log_event", AsyncMock())
        monkeypatch.setenv("BS_CUSTOM_SEARCH_ORIGINS", origin)
        monkeypatch.setenv("BS_CUSTOM_SCHEMA_ORIGINS", origin)
        monkeypatch.setenv("BS_CUSTOM_SEARCH_PORTS", str(port))
        monkeypatch.setenv("BS_CUSTOM_SEARCH_PRIVATE_CIDRS", "")

        # Preserve the real worker and its checks except this exact test address.
        run_worker = custom._run_worker
        code = (
            "import importlib.util,sys; "
            's=importlib.util.spec_from_file_location("transport",sys.argv[1]); '
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            'm.allowed=lambda address,private: address == "127.0.0.1"; m.main()'
        )
        monkeypatch.setattr(
            custom,
            "_run_worker",
            lambda payload, command: run_worker(payload, [sys.executable, "-I", "-c", code, command[-1]]),
        )

        schema = {
            "openapi": "3.0.3",
            "servers": [{"url": origin}],
            "components": {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
            "security": [{"key": []}],
            "paths": {
                "/search": {
                    "get": {
                        "parameters": [{"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}],
                        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                    }
                }
            },
        }
        imported = (await search_service.schema_preview(16, {"url": origin + "/openapi.json"}))["operations"][0]
        assert schema_requests == [None]
        assert (imported["server"], imported["path"], imported["method"]) == (origin, "/search", "GET")
        current = await search_service.get_settings(16)
        request = draft(current["revision"], {"action": "replace", "value": "test-secret"})
        assert "proof" not in imported
        request.providers["custom"]["operation"] = {
            "version": 2,
            "server": origin,
            "method": "GET",
            "path": "/search",
            "declaration": imported["declaration"],
            "media_type": "",
            "request": {"query": {"q": "{{query}}"}},
            "auth": {"location": "header", "name": "X-Key"},
            "response_mode": "raw",
        }
        saved = await search_service.put_settings(16, request, 42)
        assert saved["custom_secret_configured"]
        with sync_session() as db:
            assert "test-secret" not in db.get(GptsToolsType, 16).extra
            assert "test-secret" not in db.exec(select(WebSearchSecret)).one().ciphertext

        tool = await ToolExecutor.init_by_tool_id(
            tool_id=38, app_id="app", app_name="app", app_type=ApplicationTypeEnum.WORKFLOW, user_id=7
        )
        result = json.loads(await tool.ainvoke({"query": "hello world"}))
        assert set(result) == {"results"}
        assert (result["results"][0]["title"], result["results"][0]["url"], result["results"][0]["snippet"]) == (
            "Found",
            "https://example.org/item",
            "Text",
        )
        assert len(requests) == 1
        assert urlsplit(requests[0][0]).path == "/search"
        assert parse_qs(urlsplit(requests[0][0]).query) == {"q": ["hello world"]}
        assert requests[0][1] == "test-secret"

        monkeypatch.setattr(executor, "check_business_action", AsyncMock(return_value=False))
        with pytest.raises(PermissionError, match="Permission denied: visible"):
            await ToolExecutor.init_by_tool_id(
                tool_id=38, app_id="app", app_name="app", app_type=ApplicationTypeEnum.WORKFLOW, user_id=7
            )
        monkeypatch.setattr(executor, "check_business_action", AsyncMock(return_value=True))
        monkeypatch.setattr(executor, "get_current_tenant_id", lambda: 2)
        with pytest.raises(ToolInitializationError):
            await ToolExecutor.init_by_tool_id(
                tool_id=38, app_id="app", app_name="app", app_type=ApplicationTypeEnum.WORKFLOW, user_id=7
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        await async_engine.dispose()
        sync_engine.dispose()


def test_post_search_mapping_and_invalid_response():
    operation = {
        "server": "https://search.example/v1",
        "path": "/search",
        "method": "POST",
        "query_parameter": {"location": "body", "name": "q"},
        "fixed_params": [{"location": "query", "name": "limit", "value": 5}],
        "auth": {"location": "header", "name": "X-Key"},
    }
    request = build_request(operation, "hello", "secret")
    assert (request["url"], request["params"], request["json"], request["headers"]) == (
        "https://search.example/v1/search",
        {"limit": 5},
        {"q": "hello"},
        {"X-Key": "secret"},
    )
    mapping = {"results": "items", "title": "name", "url": "link", "snippet": "text"}
    raw = json.dumps(
        {
            "items": [
                {"name": "Found", "link": "https://example.com", "text": "secret"},
                {"name": "Invalid", "link": "javascript:alert(1)", "text": "text"},
            ]
        }
    ).encode()
    preview_data, results = map_response(raw, mapping, lambda **values: values, "secret")
    assert len(results) == 1
    assert results[0]["title"] == "Found"
    assert "secret" not in json.dumps([preview_data, results])
    assert map_response(b'{"items": []}', mapping, dict)[1] == []
    with pytest.raises(CustomSearchError):
        map_response(b"not json", mapping, dict)


@pytest.mark.parametrize("method,path,body,module,service", ROUTES)
async def test_tenant_admin_cannot_manage_root_search_settings(
    app, store, monkeypatch, method, path, body, module, service
):
    """Exercise target loading too: shared Root visibility grants no configuration access."""
    app.dependency_overrides[UserPayload.get_login_user] = lambda: SimpleNamespace(
        user_id=42, tenant_id=68, is_global_super=False
    )
    monkeypatch.setattr(identity, "get_current_tenant_id", lambda: 68)
    monkeypatch.setattr(
        identity,
        "resolve_permission_actor",
        AsyncMock(
            return_value=PermissionActor(
                user_id=42,
                current_tenant_id=68,
                tenant_admin_tenant_ids=frozenset({68}),
            )
        ),
    )
    monkeypatch.setattr(search_service, "get_current_tenant_id", lambda: 68)
    upstream = Mock(side_effect=AssertionError("foreign configuration must not reach network"))
    monkeypatch.setattr(search_service, "execute_request", upstream)
    if path == "test":
        body = {
            "draft": draft("rev", {"action": "keep"}).providers["custom"],
            "query": "q",
            "secret": {"action": "replace", "value": "temporary-test-value"},
        }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/v1/tool/16/web-search/{path}", json=body)
    assert response.status_code == 404
    upstream.assert_not_called()
    async with store() as db:
        assert (await db.exec(select(GptsToolsType))).one().extra == "{}"
        assert not (await db.exec(select(WebSearchSecret))).all()

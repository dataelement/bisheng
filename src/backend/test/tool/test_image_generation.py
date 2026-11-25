"""Core image generation journeys; HTTP and storage stay local."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from bisheng_langchain.gpts.load_tools import load_tools
from bisheng_langchain.gpts.tools.image_generation.tool import ImageGenerationError


@pytest.fixture
def upstream():
    image = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, "PNG")
    state = {"calls": [], "status": 200, "body": {"data": [{"url": "https://images.example/one.png"}]}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["calls"].append(
                (
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("x-request-id", "req-local")
            self.end_headers()
            self.wfile.write(json.dumps(state["body"]).encode())

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.update(base=f"http://127.0.0.1:{server.server_port}/v1", png=image.getvalue())
    yield state
    server.shutdown()
    server.server_close()
    worker.join()


def tool(state, *, name="image_generation", **options):
    return load_tools({name: {"openai_api_key": "test-image-key", "openai_api_base": state["base"], **options}})[0]


@pytest.mark.parametrize("name", ["image_generation", "dalle_image_generator"])
async def test_generates_with_selected_model_and_legacy_alias(upstream, name):
    instance = tool(
        upstream, name=name, model="custom-image-model", openai_api_base=upstream["base"] + "/images/generations/"
    )
    assert instance.name == name
    assert "https://images.example/one.png" in await instance.ainvoke({"query": "a blue forest"})
    assert upstream["calls"] == [
        ("/v1/images/generations", "Bearer test-image-key", {"model": "custom-image-model", "prompt": "a blue forest"})
    ]
    assert instance.args_schema.model_json_schema()["properties"].keys() == {"query"}


def test_legacy_model_default_and_azure_rejection(upstream):
    tool(upstream, name="dalle_image_generator").invoke({"query": "forest"})
    assert upstream["calls"][0][2]["model"] == "dall-e-3"
    with pytest.raises(ImageGenerationError, match="Azure"):
        tool(upstream, azure_endpoint="https://old-azure.example", azure_deployment="old-deployment")
    assert len(upstream["calls"]) == 1


async def test_base64_and_multiple_images_use_injected_storage(upstream):
    encoded = base64.b64encode(upstream["png"]).decode()
    upstream["body"] = {"data": [{"b64_json": encoded}, {"url": "https://images.example/two.png"}]}
    upload = Mock(return_value="https://storage.example/generated.png")
    result = await tool(upstream, model="another-image-model", upload_image=upload).ainvoke({"query": "forest"})
    upload.assert_called_once_with(upstream["png"], "image/png")
    assert "https://storage.example/generated.png" in result and "https://images.example/two.png" in result
    assert encoded not in result


@pytest.mark.parametrize(
    "body", [{"data": []}, {"data": [{"b64_json": "invalid!"}]}, {"data": [{"url": "javascript:alert(1)"}]}]
)
def test_invalid_response_is_failure(upstream, body):
    upstream["body"] = body
    with pytest.raises(ImageGenerationError):
        tool(upstream).invoke({"query": "forest"})


def test_provider_and_storage_errors_hide_secrets(upstream):
    upstream["status"] = 401
    upstream["body"] = {"error": {"code": "invalid_api_key", "message": "echo test-image-key"}}
    with pytest.raises(ImageGenerationError) as failed:
        tool(upstream).invoke({"query": "forest"})
    assert "401" in str(failed.value) and "req-local" in str(failed.value)
    assert "test-image-key" not in str(failed.value)
    upstream["status"] = 200
    upstream["body"] = {"data": [{"b64_json": base64.b64encode(upstream["png"]).decode()}]}
    with pytest.raises(ImageGenerationError, match="storage") as failed:
        tool(upstream, upload_image=Mock(side_effect=RuntimeError("echo test-image-key"))).invoke({"query": "forest"})
    assert "test-image-key" not in str(failed.value)
    assert len(upstream["calls"]) == 2


async def test_settings_api_persists_configuration_and_rejects_invalid_changes(upstream, monkeypatch):
    from contextlib import asynccontextmanager

    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode import BaseErrorCode
    from bisheng.tool.api.tool import router
    from bisheng.tool.domain.models import gpts_tools
    from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        for model in (GptsToolsType, GptsTools):
            await connection.run_sync(model.__table__.create)

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(gpts_tools, "get_async_db_session", session)
    # Configuration validation is isolated from the separately tested permission runtime.
    from bisheng.common.errcode.http_error import UnAuthorizedError

    edit_allowed = [True]

    async def authorize_edit(login_user, *, resource_type, resource_id, action):
        assert (resource_type, resource_id, action) == ("tool", 4, "edit")
        if not edit_allowed[0]:
            raise UnAuthorizedError()

    monkeypatch.setattr("bisheng.tool.domain.services.tool.require_business_action", authorize_edit)
    tenant = [1]
    monkeypatch.setattr("bisheng.tool.domain.services.tool.get_current_tenant_id", lambda: tenant[0])
    async with session() as db:
        db.add(
            GptsToolsType(
                id=4,
                name="legacy images",
                tenant_id=1,
                is_preset=1,
                extra=json.dumps({"openai_api_key": "test-image-key", "openai_api_base": upstream["base"]}),
            )
        )
        db.add(
            GptsTools(
                id=4,
                type=4,
                name="old",
                tool_key="dalle_image_generator",
                tenant_id=1,
                is_preset=1,
                extra=json.dumps({"model": "obsolete-child-model"}),
            )
        )
        await db.commit()

    user = UserPayload(user_id=42, user_role=[], is_global_super=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    @app.exception_handler(BaseErrorCode)
    async def handle_error(request, exc):
        return JSONResponse(status_code=200, content=exc.to_dict())

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:

            async def save(extra):
                response = await client.post("/api/v1/tool/config", json={"tool_id": 4, "extra": extra})
                assert response.status_code == 200
                return response.json()["status_code"]

            settings = {
                "openai_api_key": "********",
                "openai_api_base": upstream["base"] + "/images/generations",
                "model": "selected-model",
            }
            assert await save(settings) == 200
            saved = json.loads((await GptsToolsDao.aget_one_tool_type(4)).extra)
            assert saved["openai_api_key"] == "test-image-key" and saved["model"] == "selected-model"
            assert saved["openai_api_base"] == upstream["base"]
            assert (await GptsToolsDao.aget_one_tool(4)).extra is None
            assert not upstream["calls"]  # Saving settings must not generate a billable image.
            for change in (
                {"model": ""},
                {"openai_api_base": "https://other.example/v1"},
                {"azure_endpoint": "https://old-azure.example"},
            ):
                assert await save({**settings, **change}) == 15033
                assert json.loads((await GptsToolsDao.aget_one_tool_type(4)).extra) == saved
            edit_allowed[0] = False
            assert await save(settings) != 200
            edit_allowed[0] = True
            tenant[0] = 2
            assert await save(settings) != 200
            tenant[0] = 1
            assert json.loads((await GptsToolsDao.aget_one_tool_type(4)).extra) == saved
            assert (
                await save(
                    {**settings, "openai_api_base": "https://other.example/v1", "openai_api_key": "replacement-key"}
                )
                == 200
            )
            assert json.loads((await GptsToolsDao.aget_one_tool_type(4)).extra)["openai_api_key"] == "replacement-key"
    finally:
        await engine.dispose()


def test_legacy_child_config_is_masked():
    from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsTypeRead

    view = GptsToolsTypeRead(id=4, name="images", is_preset=1)
    view.children = [
        GptsTools(
            id=4,
            type=4,
            name="old",
            tool_key="dalle_image_generator",
            extra=json.dumps({"openai_api_key": "private-child-key"}),
        )
    ]
    view.mask_sensitive_data()
    assert "private-child-key" not in view.children[0].extra


@pytest.mark.parametrize("public_base_url", ["https://portal.example/bisheng", ""])
async def test_executor_uses_latest_config_and_authorized_tenant_storage(upstream, monkeypatch, public_base_url):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
    from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType
    from bisheng.tool.domain.services import executor
    from bisheng.tool.domain.services.executor import ToolExecutor

    category = GptsToolsType(
        id=4,
        name="images",
        tenant_id=1,
        is_preset=1,
        extra=json.dumps(
            {"openai_api_key": "test-image-key", "openai_api_base": upstream["base"], "model": "model-before"}
        ),
    )
    child = GptsTools(id=4, type=4, name="old images", tool_key="dalle_image_generator", tenant_id=1, is_preset=1)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool", AsyncMock(return_value=child))
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=category))
    permission = AsyncMock()
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", permission)
    monkeypatch.setattr(executor, "get_current_tenant_id", lambda: 2)
    monkeypatch.setattr(executor, "uses_account_availability", lambda app_type: False)
    monkeypatch.setattr(executor.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(
        "bisheng.database.models.tenant.TenantDao.get_by_id",
        lambda tenant_id: SimpleNamespace(tenant_code="acme") if tenant_id == 2 else None,
    )
    storage = Mock()
    signed_path = "/bisheng/tenant_acme/chat/42/generated.png?X-Amz-Signature=test-signature"
    storage.get_share_link_sync.return_value = (
        signed_path if public_base_url else "https://storage.example" + signed_path
    )
    monkeypatch.setattr(executor.settings.open_api, "public_base_url", public_base_url)
    monkeypatch.setattr("bisheng.core.storage.minio.minio_manager.get_minio_storage_sync", lambda: storage)
    instance = ToolExecutor.init_by_tool_instance(
        base_tool=tool(upstream, name="dalle_image_generator", model="initial-model"),
        tool=child,
        app_id="app",
        app_name="app",
        app_type=ApplicationTypeEnum.ASSISTANT,
        user_id=42,
    )
    await instance._arun(query="forest", config={})
    category.extra = json.dumps(
        {"openai_api_key": "test-image-key", "openai_api_base": upstream["base"], "model": "model-after"}
    )
    upstream["body"] = {"data": [{"b64_json": base64.b64encode(upstream["png"]).decode()}]}
    expected_url = (public_base_url or "https://storage.example") + signed_path
    assert expected_url in await instance._arun(query="forest", config={})
    assert [call[2]["model"] for call in upstream["calls"]] == ["model-before", "model-after"]
    assert instance.tool_instance.image_config["model"] == "initial-model"
    uploaded = storage.put_object_sync.call_args.kwargs
    assert uploaded["object_name"].startswith("tenant_acme/chat/42/")
    assert uploaded["file"] == upstream["png"]
    if public_base_url:
        storage.get_share_link_sync.assert_called_once_with(uploaded["object_name"])
    else:
        storage.get_share_link_sync.assert_called_once_with(uploaded["object_name"], clear_host=False)
    permission.side_effect = PermissionError("denied")
    with pytest.raises(PermissionError):
        await instance._arun(query="forest", config={})
    assert len(upstream["calls"]) == 2

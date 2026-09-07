from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers


async def test_open_api_errors_keep_v1_envelope_and_use_v2_http_status():
    app = FastAPI()
    register_open_api_exception_handlers(app)

    @app.get("/api/v1/example")
    async def v1_example():
        raise OpenApiCredentialInvalidError()

    @app.get("/api/v2/example")
    async def v2_example():
        raise OpenApiCredentialInvalidError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        v1_response = await client.get("/api/v1/example")
        v2_response = await client.get("/api/v2/example")

    assert v1_response.status_code == 200
    assert v1_response.json()["status_code"] == 26002
    assert v2_response.status_code == 401
    assert v2_response.json()["status_code"] == 26002

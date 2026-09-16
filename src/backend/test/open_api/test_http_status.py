from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.mcp_face import (
    KnowledgeCapabilityRevokedError,
    KnowledgeUnreachableError,
    RetrievalIdentityMissingError,
    RetrievalScopeTooLargeError,
)
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.common.errcode.permission import (
    PermissionInvalidResourceError,
    PermissionServiceUnavailableError,
)
from bisheng.open_api.api.exception_handlers import (
    open_api_http_status,
    register_open_api_exception_handlers,
)


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


def test_v2_business_error_transport_mapping():
    assert open_api_http_status(UnAuthorizedError()) == 403
    assert open_api_http_status(SpacePermissionDeniedError()) == 403
    assert open_api_http_status(NotFoundError()) == 404
    assert open_api_http_status(PermissionInvalidResourceError()) == 404
    assert open_api_http_status(PermissionServiceUnavailableError()) == 503


def test_mcp_face_errors_carry_their_own_transport_status():
    """F052 T002 — module 263 declares its status; the generic tail would say 400."""

    assert open_api_http_status(RetrievalIdentityMissingError()) == 403
    assert open_api_http_status(KnowledgeUnreachableError(unreachable_ids=[7])) == 404
    assert open_api_http_status(KnowledgeCapabilityRevokedError(knowledge_id=7)) == 409
    assert open_api_http_status(RetrievalScopeTooLargeError()) == 400


async def test_mcp_face_error_status_applies_on_v2_only():
    app = FastAPI()
    register_open_api_exception_handlers(app)

    @app.get("/api/v1/facade")
    async def v1_facade():
        raise KnowledgeCapabilityRevokedError(knowledge_id=7)

    @app.get("/api/v2/facade")
    async def v2_facade():
        raise KnowledgeCapabilityRevokedError(knowledge_id=7)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        v1_response = await client.get("/api/v1/facade")
        v2_response = await client.get("/api/v2/facade")

    assert v1_response.status_code == 200
    assert v1_response.json()["status_code"] == 26322
    assert v2_response.status_code == 409
    assert v2_response.json()["status_code"] == 26322
    assert v2_response.json()["data"]["knowledge_id"] == 7

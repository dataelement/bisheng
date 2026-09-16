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


async def test_mcp_face_errors_use_their_own_transport_status_on_v2():
    """263 rides the same handler as 260; the code-range fallback would say 400."""
    app = FastAPI()
    register_open_api_exception_handlers(app)

    errors = {
        "unreachable": (KnowledgeUnreachableError(unreachable_ids=[7]), 404, 26321),
        "revoked": (KnowledgeCapabilityRevokedError(knowledge_id=7), 409, 26322),
        "identity": (RetrievalIdentityMissingError(), 403, 26320),
        "too-large": (RetrievalScopeTooLargeError(), 400, 26323),
    }

    for name, (error, _status, _code) in errors.items():

        def make(exc=error):
            async def endpoint():
                raise exc

            return endpoint

        app.add_api_route(f"/api/v2/mcp-face/{name}", make(), methods=["GET"])
        app.add_api_route(f"/api/v1/mcp-face/{name}", make(), methods=["GET"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for name, (_error, status, code) in errors.items():
            v2 = await client.get(f"/api/v2/mcp-face/{name}")
            assert (v2.status_code, v2.json()["status_code"]) == (status, code)
            # Everything outside /api/v2 keeps the platform's 200 envelope.
            v1 = await client.get(f"/api/v1/mcp-face/{name}")
            assert (v1.status_code, v1.json()["status_code"]) == (200, code)


def test_v2_business_error_transport_mapping():
    assert open_api_http_status(UnAuthorizedError()) == 403
    assert open_api_http_status(KnowledgeUnreachableError(unreachable_ids=[1])) == 404
    assert open_api_http_status(KnowledgeCapabilityRevokedError(knowledge_id=1)) == 409
    assert open_api_http_status(SpacePermissionDeniedError()) == 403
    assert open_api_http_status(NotFoundError()) == 404
    assert open_api_http_status(PermissionInvalidResourceError()) == 404
    assert open_api_http_status(PermissionServiceUnavailableError()) == 503

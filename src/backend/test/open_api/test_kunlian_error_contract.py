"""昆联专用入口保留原Owner错误码与HTTP状态。"""

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient


async def test_identity_errors_keep_owner_http_status():
    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError, KunlianIdentityUnavailableError
    from bisheng.open_api.api.kunlian_dependencies import KunlianApiRoute

    app = FastAPI()
    router = APIRouter(route_class=KunlianApiRoute)

    @router.get("/identity")
    async def identity():
        raise KunlianIdentityUnavailableError()

    @router.get("/dependency")
    async def dependency():
        raise KunlianDependencyUnavailableError()

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        denied = await client.get("/identity")
        unavailable = await client.get("/dependency")
    assert (denied.status_code, denied.json()["status_code"]) == (403, 19322)
    assert (unavailable.status_code, unavailable.json()["status_code"]) == (503, 19324)


async def test_key_errors_use_owner_business_codes_not_http_numbers():
    from bisheng.open_api.api.kunlian_dependencies import KunlianApiRoute
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    app = FastAPI()
    router = APIRouter(route_class=KunlianApiRoute)

    @router.get("/key")
    async def key():
        raise KunlianAccessError("UNAUTHENTICATED")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/key")
    assert response.status_code == 401
    assert response.json()["status_code"] == 26002


async def test_runtime_failure_is_safe_http_conflict():
    from bisheng.open_api.api.kunlian_dependencies import KunlianApiRoute
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError

    app = FastAPI()
    router = APIRouter(route_class=KunlianApiRoute)

    @router.get("/run")
    async def run():
        raise RunError("IDEMPOTENCY_CONFLICT")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/run")
    assert response.status_code == 409
    assert response.json()["status_code"] == 10571

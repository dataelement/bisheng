"""昆联专用路由。局部真实 HTTP 错误合同不影响旧 SSO。"""

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger
from pydantic import Field
from starlette.exceptions import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianError,
    KunlianIdentityUnavailableError,
    KunlianLoginInvalidError,
    KunlianTrustRejectedError,
)
from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.common.schemas.api import resp_200
from bisheng.sso_sync.application.kunlian import KunlianApiBindings
from bisheng.sso_sync.domain.schemas.kunlian import KunlianContract


class KunlianRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                response = await handler(request)
            except KunlianError as error:
                response = error.to_response()
            except (UserNoRoleForLoginError, UserNoWebMenuForLoginError) as error:
                response = JSONResponse(
                    status_code=403,
                    content={"status_code": error.Code, "status_message": error.Msg, "data": None},
                )
            except RequestValidationError:
                response = KunlianLoginInvalidError().to_response()
            except AuthJWTException:
                response = JSONResponse(
                    status_code=401,
                    content={"status_code": 401, "status_message": "Authentication required", "data": None},
                )
            except HTTPException as error:
                if error.status_code == 401:
                    response = JSONResponse(
                        status_code=401,
                        content={"status_code": 401, "status_message": "Authentication required", "data": None},
                    )
                elif error.status_code == 403:
                    response = KunlianIdentityUnavailableError().to_response()
                else:
                    response = KunlianLoginInvalidError().to_response()
            # 会话响应和错误均不能进入浏览器或代理缓存。
            response.headers["Cache-Control"] = "no-store"
            return response

        return guarded


router = APIRouter(route_class=KunlianRoute, tags=["Kunlian identity integration"])


async def get_api_bindings(request: Request) -> KunlianApiBindings:
    bindings = getattr(request.app.state, "kunlian_api_bindings", None)
    if not isinstance(bindings, KunlianApiBindings):
        from bisheng.sso_sync.application.runtime import get_runtime_provider

        try:
            return await get_runtime_provider(request.app).api_bindings()
        except Exception:
            logger.error("Kunlian API runtime unavailable")
            raise KunlianDependencyUnavailableError() from None
    return bindings


@router.post("/internal/kunlian/login")
async def internal_login(request: Request, bindings: KunlianApiBindings = Depends(get_api_bindings)):
    raw, allowed = await read_gateway_body(request, bindings, "/api/v1/internal/kunlian/login")
    if bindings.login is None:
        raise KunlianDependencyUnavailableError()
    try:
        result = await bindings.login.login(
            raw,
            method=request.method,
            path="/api/v1/internal/kunlian/login",
            headers=request.headers,
            source_allowed=allowed,
        )
    except (KunlianError, UserNoRoleForLoginError, UserNoWebMenuForLoginError):
        raise
    except Exception:
        logger.error("Kunlian internal login rejected: DEPENDENCY_UNAVAILABLE")
        raise KunlianDependencyUnavailableError() from None
    return resp_200(result.gateway_payload())


async def read_gateway_body(request: Request, bindings: KunlianApiBindings, path: str):
    # 内部入口要求直接网关连接。拒绝转发头。不能信任被代理头改写的 client。
    if request.url.query or any(
        name in {"cookie", "authorization", "origin", "forwarded"} or name.startswith(("sec-fetch-", "x-forwarded-"))
        for name in request.headers
    ):
        raise KunlianTrustRejectedError()
    allowed = bindings.allows_gateway_peer(request.client.host if request.client else None)
    if not allowed:
        raise KunlianTrustRejectedError()
    raw_path = request.scope.get("raw_path", b"")
    if raw_path != path.encode("ascii"):
        raise KunlianTrustRejectedError()
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise KunlianTrustRejectedError()
        body.extend(chunk)
    return bytes(body), allowed


@router.post("/internal/kunlian/logout-ticket:redeem")
async def redeem_logout_ticket(request: Request, bindings: KunlianApiBindings = Depends(get_api_bindings)):
    path = "/api/v1/internal/kunlian/logout-ticket:redeem"
    raw, allowed = await read_gateway_body(request, bindings, path)
    if bindings.protocol is None:
        raise KunlianDependencyUnavailableError()
    return resp_200(
        await bindings.protocol.redeem(
            raw, method=request.method, path=path, headers=request.headers, source_allowed=allowed
        )
    )


@router.get("/identity-integrations/kunlian/session/csrf")
async def session_csrf(request: Request):
    from bisheng.sso_sync.application.browser import get_browser_application, resolve_browser_protocol

    admission = await resolve_browser_protocol(request)
    if admission is None:
        raise HTTPException(status_code=401)
    application = await get_browser_application(request)
    return resp_200({"auth_source": "kunlian", "csrf_token": await application.protocol.csrf(admission.reference)})


class TenantBindingRequest(KunlianContract):
    local_tenant_id: int = Field(gt=0, strict=True)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)
    enabled: bool = Field(default=True, strict=True)


def management(bindings: KunlianApiBindings):
    if bindings.management is None:
        raise KunlianDependencyUnavailableError()
    return bindings.management


@router.get("/identity-integrations/kunlian/status")
async def status(user: UserPayload = Depends(UserPayload.get_login_user), bindings=Depends(get_api_bindings)):
    return resp_200(await management(bindings).status(user))


@router.get("/identity-integrations/kunlian/tenant-bindings/{external_tenant_id}")
async def get_binding(
    external_tenant_id: str, user: UserPayload = Depends(UserPayload.get_login_user), bindings=Depends(get_api_bindings)
):
    return resp_200(await management(bindings).get_binding(user, external_tenant_id))


@router.put("/identity-integrations/kunlian/tenant-bindings/{external_tenant_id}")
async def put_binding(
    external_tenant_id: str,
    body: TenantBindingRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
    bindings=Depends(get_api_bindings),
):
    return resp_200(await management(bindings).put_binding(user, external_tenant_id, **body.model_dump()))


@router.post("/identity-integrations/kunlian/sync", status_code=202)
async def request_sync(user: UserPayload = Depends(UserPayload.get_login_user), bindings=Depends(get_api_bindings)):
    return resp_200(await management(bindings).request_sync(user))

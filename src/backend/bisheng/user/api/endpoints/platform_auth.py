"""Platform credential-owned HTTP endpoints."""

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse, RedirectResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.common.request_scope import RequestScope, request_scope
from bisheng.common.schemas.api import resp_200
from bisheng.user.domain.services.platform_origin import public_origin
from bisheng.user.domain.services.platform_transport import (
    access_credential,
    deliver,
    refresh_credential,
    require_csrf,
    require_origin,
    selected_sid,
)
from bisheng.user.platform_auth_runtime import get_platform_auth


class PlatformAuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise PlatformAuthError("invalid_auth_request") from exc
            except BaseErrorCode as exc:
                if isinstance(exc, PlatformAuthError) or request.url.path != "/api/v1/auth/login":
                    raise
                return JSONResponse(
                    exc.return_resp_instance().model_dump(),
                    status_code=password_failure_status(exc.code),
                    headers={"Cache-Control": "no-store"},
                )

        return validated


router = APIRouter(prefix="/auth", tags=["Platform authentication"], route_class=PlatformAuthRoute)


def password_failure_status(code):
    if code in {24006, 19705}:
        return 503
    if code in {10600, 10601, 10602, 10603}:
        return 401
    if code in {10609, 10611, 10620, 10621, 20001, 20003}:
        return 403
    return 400


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_name: str
    password: str
    captcha_key: str | None = None
    captcha: str | None = None
    client_id: str = "bisheng-web"
    device_label: str | None = Field(default=None, max_length=100)
    client_version: str | None = Field(default=None, max_length=64)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str | None = None
    client_id: str | None = None


@router.post("/login")
@request_scope(RequestScope.PUBLIC)
async def login(body: LoginRequest, request: Request, response: Response):
    from bisheng.common.services.config_service import settings
    from bisheng.user.application.platform_auth import issue_password_session, validate_password_identity
    from bisheng.user.domain.schemas.password_identity import PasswordLoginIdentity

    if body.client_id not in {"bisheng-web", "bisheng-mobile"}:
        raise PlatformAuthError("invalid_auth_request")
    if body.client_id == "bisheng-web":
        require_origin(request)
    elif request.cookies.get("platform_session_hint") or any(
        k.startswith(("platform_access_", "platform_refresh_")) for k in request.cookies
    ):
        raise PlatformAuthError("csrf_rejected")
    if body.client_id == "bisheng-mobile" and settings.platform_auth.mobile_cutover_ready:

        def version(value):
            try:
                return tuple(int(v) for v in (value or "0").split("+", 1)[0].split("."))
            except ValueError:
                return (0,)

        if version(body.client_version) < version(settings.platform_auth.minimum_client_version):
            raise PlatformAuthError(
                "client_upgrade_required", minimum_client_version=settings.platform_auth.minimum_client_version
            )
    identity = await validate_password_identity(
        body.model_dump(exclude={"client_id", "device_label", "client_version"}), request, response
    )
    if not isinstance(identity, PasswordLoginIdentity):
        response.status_code = password_failure_status(identity.status_code)
        response.headers["Cache-Control"] = "no-store"
        return identity
    data = await issue_password_session(identity, request, get_platform_auth(request), body)
    return resp_200(deliver(response, request, data, native=body.client_id == "bisheng-mobile"))


async def transport_refresh(request, body, service):
    cookie = refresh_credential(request)
    if cookie:
        if body.refresh_token:
            raise PlatformAuthError("credential_conflict")
        metadata = await service.logout_csrf(cookie, refresh=True)
        require_csrf(request, metadata)
        return cookie, False
    if any(
        key.startswith(("platform_refresh_", "platform_access_")) or key == "platform_session_hint"
        for key in request.cookies
    ):
        raise PlatformAuthError("csrf_rejected")
    if not body.refresh_token:
        raise PlatformAuthError("invalid_refresh_token")
    return body.refresh_token, True


@router.post("/refresh")
@request_scope(RequestScope.CREDENTIAL)
async def refresh(body: RefreshRequest, request: Request, response: Response):
    # This credential-owned endpoint also rejects conflicting selected Access
    # proofs; ambient middleware deliberately does not parse auth entrances.
    access_credential(request)
    service = get_platform_auth(request)
    credential, native = await transport_refresh(request, body, service)
    data = await service.refresh(credential)
    return resp_200(deliver(response, request, data, native=native))


@router.get("/session")
@request_scope(RequestScope.CREDENTIAL)
async def session(request: Request, response: Response):
    service = get_platform_auth(request)
    token = await service.browser_entry_token(access_credential(request), request.cookies.get("access_token_cookie"))
    if not token:
        cookie = refresh_credential(request)
        if cookie:
            await get_platform_auth(request).refresh_session(cookie)
            raise PlatformAuthError("access_expired")
        from bisheng.user.application.legacy_bridge import legacy_host_metadata

        response.headers["Cache-Control"] = "no-store"
        return resp_200(await legacy_host_metadata(request))
    data = await get_platform_auth(request).inspect(token, pending=True)
    response.headers["Cache-Control"] = "no-store"
    data.pop("access_token", None)
    return resp_200(data)


@router.get("/csrf")
@request_scope(RequestScope.CREDENTIAL)
async def csrf(request: Request, response: Response):
    if request.headers.get("origin"):
        require_origin(request)
    if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        raise PlatformAuthError("csrf_rejected")
    service = get_platform_auth(request)
    cookie = refresh_credential(request)
    token = await service.browser_entry_token(access_credential(request), request.cookies.get("access_token_cookie"))
    data = await service.refresh_session(cookie) if cookie else await service.inspect(token, pending=True)
    response.headers["Cache-Control"] = "no-store"
    return resp_200({"csrf_token": data["csrf_token"]})


@router.post("/web-bootstrap")
@request_scope(RequestScope.CREDENTIAL)
async def bootstrap(request: Request, response: Response):
    service = get_platform_auth(request)
    access_credential(request)  # Still reject a conflicting selected Cookie + Bearer.
    token = request.cookies.get("access_token_cookie") or access_credential(request)
    metadata = await service.inspect(token, pending=True)
    require_csrf(request, metadata)
    data = await service.bootstrap(token)
    return resp_200(deliver(response, request, data))


@router.post("/logout")
@request_scope(RequestScope.CREDENTIAL)
async def logout(request: Request, response: Response, body: RefreshRequest | None = None):
    service = get_platform_auth(request)
    cookie = refresh_credential(request)
    token = access_credential(request, gateway=True)
    if (
        body
        and body.refresh_token
        and (
            token
            or cookie
            or selected_sid(request)
            or any(k.startswith(("platform_access_", "platform_refresh_")) for k in request.cookies)
        )
    ):
        raise PlatformAuthError("credential_conflict")
    credential = cookie or (body.refresh_token if body else None) or token
    if credential:
        if cookie or selected_sid(request) or request.cookies.get("access_token_cookie"):
            metadata = await service.logout_csrf(cookie or token, refresh=bool(cookie))
            require_csrf(request, metadata)
        await service.logout(credential, refresh=bool(cookie or (body and body.refresh_token)))
    sid = selected_sid(request)
    if sid:
        response.delete_cookie(f"platform_access_{sid}", path="/")
        response.delete_cookie(f"platform_refresh_{sid}", path="/api/v1/auth")
    response.headers["Cache-Control"] = "no-store"
    return resp_200()


@router.post("/logout-all")
@request_scope(RequestScope.CREDENTIAL)
async def logout_all(request: Request, response: Response):
    service = get_platform_auth(request)
    token = access_credential(request)
    metadata = await service.inspect(token)
    if selected_sid(request):
        require_csrf(request, metadata)
    await service.logout(token, all_sessions=True)
    response.headers["Cache-Control"] = "no-store"
    return resp_200()


@router.post("/web-session")
@request_scope(RequestScope.CREDENTIAL)
async def web_session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return resp_200(await get_platform_auth(request).create_ticket(access_credential(request), public_origin(request)))


@router.get("/web-session/consume")
@request_scope(RequestScope.CREDENTIAL)
async def consume(ticket: str, request: Request):
    data = await get_platform_auth(request).consume_ticket(ticket, public_origin(request))
    response = RedirectResponse("/workspace", status_code=303)
    deliver(response, request, data)
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

"""Mobile routes return the bare shapes required by the desktop and phone clients."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocket

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.mobile_access import MobileAccessService, MobileResult
from bisheng.dsh.domain.services.mobile_session import MobileSessionService, build_mobile_session_service
from bisheng.dsh.infrastructure.mobile_access import MobileAccessStore

router = APIRouter()
_service: MobileAccessService | None = None
_sessions: MobileSessionService | None = None


async def mobile_sessions(request: Request) -> MobileSessionService:
    override = getattr(request.app.state, "mobile_sessions", None)
    if override is not None:
        return override
    global _sessions
    if _sessions is None:
        _sessions = build_mobile_session_service()
    return _sessions


async def mobile_service() -> MobileAccessService:
    global _service
    if _service is None:
        from bisheng.core.cache.redis_manager import get_redis_client

        redis = (await get_redis_client()).async_connection
        _service = MobileAccessService(MobileAccessStore(redis))
    return _service


@router.post("/dsh/mobile/bind")
async def bind(
    request: Request,
    principal: DshPrincipal = Depends(desktop_principal),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()
    return _respond(await service.bind(_desktop_account(principal), body))


@router.post("/dsh/mobile/unbind")
async def unbind(
    request: Request,
    principal: DshPrincipal = Depends(desktop_principal),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()
    return _respond(await service.unbind(_desktop_account(principal), body))


@router.post("/dsh/mobile/session")
async def open_mobile_session(
    user=Depends(UserPayload.get_login_user),
    service: MobileSessionService = Depends(mobile_sessions),
):
    try:
        data = await service.open(user.user_id, user.tenant_id, getattr(user, "user_name", None))
    except BaseErrorCode as error:
        return _failure(error)
    return resp_200(data)


@router.post("/dsh/mobile/session/refresh")
async def refresh_mobile_session(
    request: Request,
    service: MobileSessionService = Depends(mobile_sessions),
):
    body = await _object_body(request)
    if body is None:
        return _failure(DshInvalidRequestError())
    refresh = body.get("refresh_token")
    try:
        data = await service.refresh(refresh if isinstance(refresh, str) else None)
    except BaseErrorCode as error:
        return _failure(error)
    return resp_200(data)


@router.delete("/dsh/mobile/session")
async def revoke_mobile_session(
    request: Request,
    service: MobileSessionService = Depends(mobile_sessions),
):
    body = await _object_body(request)
    refresh = body.get("refresh_token") if isinstance(body, dict) else None
    if isinstance(refresh, str):
        await service.revoke(refresh)
    return Response(status_code=204)


@router.get("/dsh/mobile/desktops")
async def desktops(
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    return _respond(await service.list_desktops(user))


@router.post("/dsh/mobile/desktops/{desktop_id}/rpc")
async def rpc(
    desktop_id: str,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()
    return _respond(await service.rpc(user, desktop_id, body))


@router.websocket("/dsh/mobile/attach")
async def attach(websocket: WebSocket, service: MobileAccessService = Depends(mobile_service)):
    client = websocket.client.host if websocket.client else "unknown"
    await service.attach(websocket, client)


async def _object_body(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _respond(result: MobileResult):
    if result.raw and isinstance(result.body, str):
        return Response(
            content=result.body,
            status_code=result.status,
            media_type=result.media_type or "application/json",
        )
    return JSONResponse(status_code=result.status, content=result.body)


class _DesktopAccount:
    """Registration stores integer account ids. Desktop tokens carry decimal strings."""

    def __init__(self, user_id: int, tenant_id: int):
        self.user_id = user_id
        self.tenant_id = tenant_id


def _desktop_account(principal: DshPrincipal) -> _DesktopAccount:
    return _DesktopAccount(user_id=int(principal.user_id), tenant_id=int(principal.tenant_id))


def _invalid() -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_request"})


def _failure(error: BaseErrorCode) -> JSONResponse:
    return JSONResponse(
        status_code=getattr(error, "HttpStatus", 401),
        content={
            "status_code": error.Code,
            "status_message": error.Msg,
            "error": getattr(error, "ClientCode", "unauthorized"),
        },
    )

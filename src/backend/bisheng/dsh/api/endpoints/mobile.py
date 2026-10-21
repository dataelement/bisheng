"""Mobile routes return the bare shapes required by the desktop and phone clients."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocket

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.dsh.domain.services.mobile_access import MobileAccessService, MobileResult
from bisheng.dsh.infrastructure.mobile_access import MobileAccessStore

router = APIRouter()
_service: MobileAccessService | None = None


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
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()
    return _respond(await service.bind(user, body))


@router.post("/dsh/mobile/unbind")
async def unbind(
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()
    return _respond(await service.unbind(user, body))


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


def _invalid() -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_request"})

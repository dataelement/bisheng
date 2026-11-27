"""Mobile routes return the bare shapes required by the desktop and phone clients."""

import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from starlette.websockets import WebSocket

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.common.request_scope import RequestScope, request_scope
from bisheng.common.schemas.api import resp_200
from bisheng.core.session_activity import business_activity, record_authenticated_activity
from bisheng.dsh.api.dependencies import desktop_principal
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.mobile_access import MobileAccessService, MobileResult, MobileStream
from bisheng.dsh.domain.services.mobile_session import MobileSessionService, build_mobile_session_service
from bisheng.dsh.infrastructure.mobile_access import MobileAccessStore

router = APIRouter()
_service: MobileAccessService | None = None
_blocking_redis = None
_service_lock = asyncio.Lock()
_sessions: MobileSessionService | None = None


class MobileStreamingResponse(StreamingResponse):
    """Relays one desktop stream and always runs its cleanup.

    A phone that walks away cancels this response, which cancels the body
    generator. The shield keeps the cancel frame and the slot release going
    through anyway; otherwise the desktop keeps its Harness follow open.
    """

    def __init__(self, stream: MobileStream):
        self._stream = stream
        super().__init__(
            stream.body,
            status_code=stream.status,
            media_type=stream.media_type,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.shield(self._stream.close())


async def mobile_sessions(request: Request) -> MobileSessionService:
    from bisheng.common.services.config_service import settings

    if settings.platform_auth.mobile_cutover_ready:
        from bisheng.common.errcode.platform_auth import PlatformAuthError

        raise PlatformAuthError(
            "client_upgrade_required", minimum_client_version=settings.platform_auth.minimum_client_version
        )
    override = getattr(request.app.state, "mobile_sessions", None)
    if override is not None:
        return override
    global _sessions
    if _sessions is None:
        _sessions = build_mobile_session_service()
    return _sessions


async def mobile_service() -> MobileAccessService:
    global _service, _blocking_redis
    if _service is not None:
        return _service
    async with _service_lock:
        if _service is not None:
            return _service
        from bisheng.common.services.config_service import settings
        from bisheng.core.cache.redis_conn import RedisClient
        from bisheng.core.cache.redis_manager import get_redis_client

        shared = (await get_redis_client()).async_connection
        # Construction connects a cluster immediately, so it stays off the event loop.
        # RedisClient already branches for a single node, cluster, and sentinel.
        creation = asyncio.create_task(asyncio.to_thread(RedisClient, settings.redis_url, max_connections=64))
        try:
            client = await asyncio.shield(creation)
        except asyncio.CancelledError:
            # Cancelling to_thread does not stop its constructor. Close the
            # eventual unpublished client instead of leaking its connections.
            async def close_unpublished():
                try:
                    unpublished = await creation
                except Exception:
                    logger.exception("mobile stream redis initialization failed after cancellation")
                    return
                await _close_mobile_redis(unpublished)

            await asyncio.shield(close_unpublished())
            raise
        _blocking_redis = client
        _service = MobileAccessService(MobileAccessStore(shared, client.async_connection))
    return _service


async def close_mobile_service() -> None:
    """Releases the stream-only Redis client at shutdown.

    ``aclose`` only closes the async side; the constructor also opened a sync
    connection, which leaks a client per process without ``close``. Never
    raises: shutdown continues with the rest of the teardown.
    """
    global _service, _blocking_redis
    async with _service_lock:
        client, _blocking_redis, _service = _blocking_redis, None, None
    if client is None:
        return
    await _close_mobile_redis(client)


async def _close_mobile_redis(client) -> None:
    try:
        await client.aclose()
    except Exception:
        logger.warning("mobile stream redis async close failed")
    try:
        await asyncio.to_thread(client.close)
    except Exception:
        logger.warning("mobile stream redis close failed")


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
@request_scope(RequestScope.IDENTITY)
async def desktops(
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    return _respond(await service.list_desktops(user))


@router.post("/dsh/mobile/desktops/{desktop_id}/rpc")
@request_scope(RequestScope.IDENTITY)
@business_activity(
    http=False,
    rpc_methods=(
        "session.prompt",
        "session.create",
        "session.cancel",
        "interaction.answer",
        "interaction.cancel",
        "session.uploadStart",
        "session.uploadChunk",
        "session.uploadFinish",
    ),
)
async def rpc(
    desktop_id: str,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    body = await _object_body(request)
    if body is None:
        return _invalid()

    async def before_dispatch():
        reference = getattr(user, "_runtime_credential_reference", None)
        if reference and reference.get("kind") == "platform_session":
            await record_authenticated_activity(request, message=body)

    return _respond(await service.rpc(user, desktop_id, body, before_dispatch=before_dispatch))


@router.get("/dsh/mobile/desktops/{desktop_id}/session/stream")
@request_scope(RequestScope.IDENTITY)
async def session_stream(
    desktop_id: str,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
    service: MobileAccessService = Depends(mobile_service),
):
    opened = await service.open_session_stream(
        user,
        desktop_id,
        request.query_params.get("sessionId"),
        request.query_params.get("view"),
    )
    if isinstance(opened, MobileResult):
        return _respond(opened)
    if not isinstance(opened, MobileStream):
        return JSONResponse(status_code=503, content={"error": "unavailable"})
    return MobileStreamingResponse(opened)


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

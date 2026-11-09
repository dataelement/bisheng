"""Fixed account-private project API; the authenticated user selects the actor."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import ValidationError

from bisheng.chat_session.domain.schemas.projects import PROJECT_ACTION_ADAPTER
from bisheng.chat_session.domain.services.project_events import project_event_stream
from bisheng.chat_session.domain.services.project_service import ChatProjectService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.chat import ProjectInputError
from bisheng.common.schemas.api import resp_200
from bisheng.user.domain.services.auth import AuthJwt

router = APIRouter(prefix="/chat/projects")


@router.get("/snapshot")
async def snapshot(
    cursor: str | None = Query(default=None, max_length=2048), user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(await ChatProjectService.snapshot(ChatProjectService.actor(user), cursor))


@router.post("/actions")
async def action(request: Request, user: UserPayload = Depends(UserPayload.get_login_user)):
    # Bound the actual body, not a caller-supplied Content-Length header.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise ProjectInputError()
    try:
        operation = PROJECT_ACTION_ADAPTER.validate_json(bytes(body))
    except (ValidationError, ValueError) as exc:
        raise ProjectInputError() from exc
    return resp_200(await ChatProjectService.execute(ChatProjectService.actor(user), operation))


@router.get("/conversations")
async def conversations(
    project_id: UUID | None = None,
    query: str = Query(default="", max_length=255),
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=40, ge=1, le=100),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await ChatProjectService.conversations(
            ChatProjectService.actor(user),
            project_id=str(project_id) if project_id else None,
            query=query,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/events")
async def events(
    request: Request, user: UserPayload = Depends(UserPayload.get_login_user), auth_jwt: AuthJwt = Depends()
):
    actor = ChatProjectService.actor(user)

    async def authenticate():
        try:
            # Decode again to enforce expiry during a long-lived connection;
            # also check current account state and revocation, not just JWT claims.
            current = await UserPayload.get_login_user(auth_jwt)
            return await ChatProjectService.identity_active(actor, current)
        except Exception:
            logger.opt(exception=True).warning("project-sync credential revalidation failed; closing subscription")
            return False

    async def version():
        return await ChatProjectService.version(actor)

    return StreamingResponse(
        project_event_stream(actor, version, authenticate, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

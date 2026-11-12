"""Fixed account-private project API; the authenticated user selects the actor."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from bisheng.chat_session.domain.schemas.projects import PROJECT_ACTION_ADAPTER
from bisheng.chat_session.domain.services.project_service import ChatProjectService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.chat import ProjectInputError
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/chat/projects")


@router.get("/snapshot")
async def snapshot(user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await ChatProjectService.snapshot(ChatProjectService.actor(user)))


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
    cursor: str | None = Query(default=None, max_length=16),
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

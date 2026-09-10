"""Browser JWT endpoints restricted to the current natural person."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.services.self_service import DshSelfService

router = APIRouter(prefix="/dsh/me", route_class=DshRoute)


def self_service(runtime=Depends(get_runtime)):
    return DshSelfService(runtime)


@router.get("/profile")
async def profile(user=Depends(UserPayload.get_login_user), service=Depends(self_service)):
    return resp_200(data=await service.profile(user))


@router.get("/sessions")
async def sessions(
    user=Depends(UserPayload.get_login_user),
    service=Depends(self_service),
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return resp_200(data=await service.sessions(user, cursor=cursor, limit=limit))


@router.post("/sessions/{session_id}/revoke")
async def revoke(
    session_id: UUID, request: Request, user=Depends(UserPayload.get_login_user), service=Depends(self_service)
):
    if (
        request.headers.get("origin") != service.runtime.settings.platform_public_url
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
        or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"
    ):
        raise HTTPException(403, "Invalid browser origin")
    return resp_200(data=await service.revoke(user, str(session_id)))


@router.get("/usage")
async def usage(user=Depends(UserPayload.get_login_user), service=Depends(self_service)):
    return resp_200(data=await service.usage(user))

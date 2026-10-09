"""Browser JWT endpoints restricted to the current natural person."""

from fastapi import APIRouter, Depends

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


@router.get("/usage")
async def usage(user=Depends(UserPayload.get_login_user), service=Depends(self_service)):
    return resp_200(data=await service.usage(user))


@router.get("/usage-summary")
async def usage_summary(user=Depends(UserPayload.get_login_user), service=Depends(self_service)):
    return resp_200(data=await service.usage_summary(user))

from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfigUpdate, HttpMethod
from bisheng.api_rate_limit.domain.services import ApiRateLimitService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/admin/api-rate-limit", tags=["api-rate-limit"])


@router.get("/config")
async def get_api_rate_limit_config(
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(data=await ApiRateLimitService.get_config(user))


@router.put("/config")
async def update_api_rate_limit_config(
    payload: ApiRateLimitConfigUpdate = Body(...),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(data=await ApiRateLimitService.update_config(user, payload))


@router.get("/routes")
async def get_api_rate_limit_routes(
    request: Request,
    keyword: str | None = Query(default=None, max_length=200),
    method: HttpMethod | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        data=await ApiRateLimitService.get_route_catalog(
            user,
            request.app.router.routes,
            keyword=keyword,
            method=method,
            tag=tag,
            page=page,
            page_size=page_size,
        )
    )

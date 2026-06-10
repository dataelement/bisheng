from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenCreate,
    DeveloperTokenGlobalConfig,
    DeveloperTokenListQuery,
    DeveloperTokenUpdate,
)
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.utils import get_request_ip

router = APIRouter(prefix="/admin/developer-tokens", tags=["developer-token"])


def _request_context(request: Request) -> dict:
    return {
        "request_ip": get_request_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


@router.get("")
async def list_developer_tokens(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None),
    tenant_id: int | None = Query(None),
    user_id: int | None = Query(None),
    enabled: bool | None = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.list_tokens(
        login_user,
        DeveloperTokenListQuery(
            page=page,
            limit=limit,
            keyword=keyword,
            tenant_id=tenant_id,
            user_id=user_id,
            enabled=enabled,
        ),
    )
    return resp_200(data=data)


@router.post("")
async def create_developer_token(
    request: Request,
    payload: DeveloperTokenCreate = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.create_token(
        login_user,
        payload,
        **_request_context(request),
    )
    return resp_200(data=data)


@router.get("/config/global")
async def get_developer_token_global_config(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.get_global_config(login_user)
    return resp_200(data=data)


@router.put("/config/global")
async def update_developer_token_global_config(
    request: Request,
    payload: DeveloperTokenGlobalConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.update_global_config(
        login_user,
        payload,
        **_request_context(request),
    )
    return resp_200(data=data)


@router.get("/{token_id}")
async def get_developer_token_detail(
    token_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.get_token_detail(token_id, login_user)
    return resp_200(data=data)


@router.put("/{token_id}")
async def update_developer_token(
    token_id: int,
    request: Request,
    payload: DeveloperTokenUpdate = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.update_token(
        token_id,
        login_user,
        payload,
        **_request_context(request),
    )
    return resp_200(data=data)


@router.delete("/{token_id}")
async def delete_developer_token(
    token_id: int,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    await DeveloperTokenService.delete_token(
        token_id,
        login_user,
        **_request_context(request),
    )
    return resp_200()


@router.get("/{token_id}/secret")
async def view_developer_token_secret(
    token_id: int,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await DeveloperTokenService.view_secret(
        token_id,
        login_user,
        **_request_context(request),
    )
    return resp_200(data=data)

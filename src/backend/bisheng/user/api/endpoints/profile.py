"""Authenticated natural-person profile changes."""

from fastapi import APIRouter, Depends, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.user.domain.schemas.nickname import NicknameActor, NicknameUpdateRequest
from bisheng.user.domain.services.nickname_service import NicknameService
from bisheng.utils import get_request_ip

router = APIRouter()


@router.patch("/user/profile/nickname")
async def update_my_nickname(
    request: Request,
    data: NicknameUpdateRequest,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    actor = NicknameActor(
        user_id=user.user_id,
        user_name=user.user_name or "",
        tenant_id=get_current_tenant_id() or user.tenant_id,
        ip_address=get_request_ip(request),
    )
    try:
        saved = await NicknameService.arename_self(actor, data.user_name)
    except BaseErrorCode as error:
        return error.return_resp_instance(data=error.kwargs or None)
    return resp_200({"user_id": saved.user_id, "user_name": saved.user_name, "external_id": saved.external_id})

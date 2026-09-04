"""JWT-authenticated personal-token self service."""

from fastapi import APIRouter, Depends, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.open_api.domain.schemas.personal_token import (
    PersonalTokenInstallPrompt,
    PersonalTokenIssued,
    PersonalTokenStatus,
)
from bisheng.open_api.domain.services.personal_token_service import PersonalTokenService

router = APIRouter(prefix="/me/api-token", tags=["PersonalToken"])


def _tenant_id(user: UserPayload) -> int:
    return int(get_current_tenant_id() or user.tenant_id)


@router.get("", response_model=UnifiedResponseModel[PersonalTokenStatus])
async def get_personal_token_status(user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await PersonalTokenService.status(tenant_id=_tenant_id(user), user_id=user.user_id))


@router.post("", response_model=UnifiedResponseModel[PersonalTokenIssued])
async def issue_personal_token(user: UserPayload = Depends(UserPayload.get_login_user)):
    issued = await PersonalTokenService.issue(
        tenant_id=_tenant_id(user),
        user_id=user.user_id,
        operator=user,
    )
    return resp_200(data=issued)


@router.delete("", response_model=UnifiedResponseModel[dict])
async def delete_personal_token(user: UserPayload = Depends(UserPayload.get_login_user)):
    revoked = await PersonalTokenService.revoke_self(
        tenant_id=_tenant_id(user),
        user_id=user.user_id,
        operator=user,
    )
    return resp_200(data={"revoked": revoked})


@router.get("/install-prompt", response_model=UnifiedResponseModel[PersonalTokenInstallPrompt])
async def get_install_prompt(
    request: Request,
    _user: UserPayload = Depends(UserPayload.get_login_user),
):
    pack_url = str(request.url_for("download_open_api_skill_pack", pack_name="bisheng-knowledge-search"))
    prompt = (
        "Install the BiSheng knowledge-search skill from "
        f"{pack_url} and configure its BISHENG_API_KEY environment variable with my personal access token."
    )
    return resp_200(data=PersonalTokenInstallPrompt(prompt=prompt, skill_pack_url=pack_url))


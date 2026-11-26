from fastapi import APIRouter, Depends, Path

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.application.provider_instance_admin import create_instance, list_instances, update_instance
from bisheng.knowledge.domain.schemas.provider_instance import (
    ProviderInstanceUpdate,
    ProviderInstanceView,
    ProviderInstanceWrite,
)

router = APIRouter(prefix="/provider-instances", tags=["Knowledge"])


@router.get("", response_model=UnifiedResponseModel[list[ProviderInstanceView]])
async def get_provider_instances(identity: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await list_instances(identity))


@router.post("", response_model=UnifiedResponseModel[ProviderInstanceView])
async def post_provider_instance(
    body: ProviderInstanceWrite,
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await create_instance(identity, body))


@router.patch("/{instance_id}", response_model=UnifiedResponseModel[ProviderInstanceView])
async def patch_provider_instance(
    body: ProviderInstanceUpdate,
    instance_id: int = Path(gt=0, le=2**63 - 1),
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await update_instance(identity, instance_id, body))

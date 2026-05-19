from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
    SensitiveWordPolicyPayload,
)
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)

router = APIRouter(prefix='/sensitive-word-policies', tags=['sensitive-word-policies'])


@router.get('/{business_type}')
async def get_sensitive_word_policy(
    business_type: SensitiveWordBusinessType,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    policy = await SensitiveWordPolicyService.aget_policy(login_user, business_type)
    return resp_200(policy.model_dump())


@router.put('/{business_type}')
async def update_sensitive_word_policy(
    business_type: SensitiveWordBusinessType,
    payload: SensitiveWordPolicyPayload,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    policy = await SensitiveWordPolicyService.aupsert_policy(login_user, business_type, payload)
    return resp_200(policy.model_dump())

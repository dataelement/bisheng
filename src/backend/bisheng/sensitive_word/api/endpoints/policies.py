from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.common.schemas.api import resp_200
from bisheng.sensitive_word.domain.schemas import (
    SensitiveWordBusinessType,
    SensitiveWordPolicyPayload,
)
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import (
    SensitiveWordPolicyService,
)
from bisheng.user.domain.services.platform_operator import can_platform_operate

router = APIRouter(prefix='/sensitive-word-policies', tags=['sensitive-word-policies'])


def _require_policy_operator(login_user: UserPayload) -> UserPayload:
    """敏感词策略读写: 超管或运营岗. 不扩大 get_tenant_admin_user."""
    if not can_platform_operate(login_user):
        raise LLMModelSharedReadonlyError()
    return login_user


@router.get('/{business_type}')
async def get_sensitive_word_policy(
    business_type: SensitiveWordBusinessType,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _require_policy_operator(login_user)
    policy = await SensitiveWordPolicyService.aget_policy(login_user, business_type)
    return resp_200(policy.model_dump())


@router.put('/{business_type}')
async def update_sensitive_word_policy(
    business_type: SensitiveWordBusinessType,
    payload: SensitiveWordPolicyPayload,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    _require_policy_operator(login_user)
    policy = await SensitiveWordPolicyService.aupsert_policy(login_user, business_type, payload)
    return resp_200(policy.model_dump())

"""Shared enterprise model permissions and personal credit allowances."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.api.endpoints.admin import TenantId, UserId, get_management
from bisheng.dsh.api.endpoints.models import billing_period
from bisheng.dsh.domain.schemas.unified_policy import (
    CreditRuleInput,
    ModelVisibilityInput,
    PolicySubject,
    credit_balance,
)
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.unified_policy import policy_transaction
from bisheng.dsh.runtime import get_model_runtime, read_policy

router = APIRouter(prefix="/dsh")
admin_user = UserPayload.get_tenant_admin_user


@router.get("/admin/models/{model_id}/visibility")
async def visibility(
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        from bisheng.llm.domain.services.llm import LLMService

        await LLMService.get_dsh_model_metadata_snapshot(model_id)
        return resp_200(data=await policy_transaction(lambda repo: repo.visibility(model_id)))


@router.put("/admin/models/{model_id}/visibility")
async def save_visibility(
    model_id: UserId,
    body: ModelVisibilityInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        from bisheng.llm.domain.services.llm import LLMService

        await LLMService.get_dsh_model_metadata_snapshot(model_id)
        return resp_200(data=await policy_transaction(lambda repo: repo.save_visibility(model_id, user.user_id, body)))


@router.get("/admin/credit-rules")
async def credit_rules(
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        return resp_200(data=await policy_transaction(lambda repo: repo.rules()))


@router.get("/admin/policy-subjects")
async def policy_subjects(
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        return resp_200(data=await policy_transaction(lambda repo: repo.subject_options()))


@router.put("/admin/credit-rules/{subject_type}/{subject_id}")
async def save_credit_rule(
    subject_type: Literal["DEPARTMENT", "ROLE", "USER"],
    subject_id: UserId,
    body: CreditRuleInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    subject = PolicySubject(kind=subject_type, id=subject_id)
    _, tenant = await service.authorize(
        user.user_id, tenant_id or get_current_tenant_id(), subject_id if subject_type == "USER" else None
    )
    with profile_scope(tenant):
        return resp_200(data=await policy_transaction(lambda repo: repo.save_rule(subject, user.user_id, body)))


@router.get("/me/credits")
async def personal_credits(user=Depends(UserPayload.get_login_user), runtime=Depends(get_runtime)):
    from types import SimpleNamespace

    from bisheng.dsh.domain.services.self_service import DshSelfService

    await DshSelfService(runtime).identity(user)
    period = billing_period(datetime.now(UTC), runtime.settings.billing_timezone)
    with profile_scope(user.tenant_id):
        policy = await read_policy(user.user_id)
        service = await get_model_runtime(runtime)
        snapshot = await service.prepare_month(
            SimpleNamespace(tenant_id=user.tenant_id, user_id=user.user_id), period["month"]
        )
    used = snapshot["used"] if snapshot.get("quota_state") == "ready" else None
    return resp_200(data={**period, **credit_balance(limit=policy.monthly_token_limit, used=used)})

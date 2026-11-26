"""Shared enterprise model permissions and personal credit allowances."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

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
from bisheng.dsh.domain.services.unified_policy import policy_transaction, with_visibility_avatars
from bisheng.dsh.runtime import get_model_runtime, read_policy

router = APIRouter(prefix="/dsh")
admin_user = UserPayload.get_tenant_admin_user


class _PlatformPolicyAdmin:
    """Model visibility administration when DSH is not deployed.

    Visibility belongs to the platform (who may pick a model in the workbench);
    only credits need DSH. Authorization is the same tenant-admin check DSH uses.
    """

    @staticmethod
    async def authorize(actor_id: int, tenant_id: int | None):
        from bisheng.dsh.admin_runtime import authorize_admin

        return await authorize_admin(actor_id, tenant_id)


async def get_policy_admin(request: Request):
    """DSH management when deployed; otherwise platform tenant-admin authorization."""
    from bisheng.common.services.config_service import settings

    if not settings.dsh.enabled:
        return _PlatformPolicyAdmin()
    return await get_management(await get_runtime(request, settings.dsh))


def _missing_row_visible_to_everyone() -> bool:
    """Every online model is offered until an administrator narrows it."""
    return True


@router.get("/admin/models/{model_id}/visibility")
async def visibility(
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_policy_admin),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        from bisheng.llm.domain.services.llm import LLMService

        await LLMService.get_dsh_model_metadata_snapshot(model_id)
        default_everyone = _missing_row_visible_to_everyone()
        payload = await policy_transaction(lambda repo: repo.visibility(model_id, default_everyone=default_everyone))
        return resp_200(data=await with_visibility_avatars(payload, tenant))


@router.put("/admin/models/{model_id}/visibility")
async def save_visibility(
    model_id: UserId,
    body: ModelVisibilityInput,
    user=Depends(admin_user),
    service=Depends(get_policy_admin),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant):
        from bisheng.llm.domain.services.llm import LLMService

        await LLMService.get_dsh_model_metadata_snapshot(model_id)
        payload = await policy_transaction(lambda repo: repo.save_visibility(model_id, user.user_id, body))
        return resp_200(data=await with_visibility_avatars(payload, tenant))


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
    service=Depends(get_policy_admin),
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


async def month_credits(runtime, tenant_id: int, user_id: int, preview: CreditRuleInput | None = None) -> dict:
    """One balance for the member's own view and the administrator's usage page.

    ``preview``: the balance if the member's own credit rule were saved as given (the rule editor).
    """
    from types import SimpleNamespace

    period = billing_period(datetime.now(UTC), runtime.settings.billing_timezone)
    with profile_scope(tenant_id):
        if preview is None:
            limit = (await read_policy(user_id)).monthly_token_limit
        else:
            limit = await policy_transaction(lambda repo: repo.preview_user_limit(user_id, preview))
        service = await get_model_runtime(runtime)
        snapshot = await service.prepare_month(SimpleNamespace(tenant_id=tenant_id, user_id=user_id), period["month"])
    used = snapshot["used"] if snapshot.get("quota_state") == "ready" else None
    return {**period, **credit_balance(limit=limit, used=used)}


@router.get("/me/credits")
async def personal_credits(user=Depends(UserPayload.get_login_user), runtime=Depends(get_runtime)):
    from bisheng.dsh.domain.services.self_service import DshSelfService

    await DshSelfService(runtime).identity(user)
    return resp_200(data=await month_credits(runtime, user.tenant_id, user.user_id))


@router.get("/admin/users/{user_id}/credits")
async def user_credits(
    user_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    runtime=Depends(get_runtime),
    tenant_id: TenantId = None,
    monthly_credits: Annotated[str | None, Query(max_length=16)] = None,
    enabled: bool = True,
):
    """``monthly_credits`` (and ``enabled``): preview the balance with the member's own rule set so."""
    preview = None
    if monthly_credits is not None:
        try:
            preview = CreditRuleInput(version=0, monthly_credits=monthly_credits, enabled=enabled)
        except ValidationError as error:
            raise RequestValidationError(error.errors(include_url=False, include_context=False)) from error
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id(), user_id)
    return resp_200(data=await month_credits(runtime, tenant, user_id, preview))

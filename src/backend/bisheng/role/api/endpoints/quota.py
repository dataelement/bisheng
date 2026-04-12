"""Quota query endpoints.

Part of F005-role-menu-quota. Implements AC-15~AC-19.
"""

from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.user.domain.services.auth import LoginUser

router = APIRouter(prefix='/quota')


@router.get('/effective', response_model=UnifiedResponseModel)
async def get_effective_quota(
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Get current user's effective quota for all resource types (AC-15~AC-19)."""
    items = await QuotaService.get_all_effective_quotas(
        user_id=login_user.user_id,
        tenant_id=login_user.tenant_id,
        login_user=login_user,
    )
    return resp_200(data=[item.model_dump() for item in items])


@router.get('/usage', response_model=UnifiedResponseModel)
async def get_resource_usage(
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Get current user's resource usage counts (AC-15)."""
    import asyncio
    from bisheng.role.domain.services.quota_service import DEFAULT_ROLE_QUOTA

    resource_types = list(DEFAULT_ROLE_QUOTA.keys())
    counts = await asyncio.gather(*(
        QuotaService.get_user_resource_count(login_user.user_id, rt)
        for rt in resource_types
    ))
    usage = dict(zip(resource_types, counts))
    return resp_200(data=usage)

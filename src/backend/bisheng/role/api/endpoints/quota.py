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
    from bisheng.role.domain.services.quota_service import DEFAULT_ROLE_QUOTA

    usage = {}
    for resource_type in DEFAULT_ROLE_QUOTA:
        usage[resource_type] = await QuotaService.get_user_resource_count(
            login_user.user_id, resource_type,
        )
    return resp_200(data=usage)

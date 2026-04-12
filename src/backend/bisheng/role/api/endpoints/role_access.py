"""Role menu permission endpoints.

Part of F005-role-menu-quota. Implements AC-11, AC-12.
"""

from typing import List

from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.role.domain.schemas.role_schema import MenuUpdateRequest
from bisheng.role.domain.services.role_service import RoleService
from bisheng.user.domain.services.auth import LoginUser

router = APIRouter(prefix='/roles')


@router.post('/{role_id}/menu', response_model=UnifiedResponseModel)
async def update_role_menu(
    role_id: int,
    req: MenuUpdateRequest,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Update role menu permissions (AC-11)."""
    await RoleService.update_menu(role_id, req.menu_ids, login_user)
    return resp_200(data=None)


@router.get('/{role_id}/menu', response_model=UnifiedResponseModel)
async def get_role_menu(
    role_id: int,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Get role menu permissions (AC-12)."""
    menus = await RoleService.get_menu(role_id, login_user)
    return resp_200(data=menus)

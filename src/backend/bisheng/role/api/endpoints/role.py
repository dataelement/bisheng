"""Role CRUD endpoints.

Part of F005-role-menu-quota. Implements AC-01~AC-10c.
"""

from fastapi import APIRouter, Depends, Query, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.role.domain.schemas.role_schema import RoleCreateRequest, RoleUpdateRequest
from bisheng.role.domain.services.role_service import RoleService
from bisheng.user.domain.services.auth import LoginUser
from bisheng.utils import get_request_ip

router = APIRouter(prefix='/roles')


def _audit_log_service():
    from bisheng.api.services.audit_log import AuditLogService
    return AuditLogService


@router.post('', response_model=UnifiedResponseModel)
async def create_role(
    request: Request,
    req: RoleCreateRequest,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Create a new role (AC-01, AC-02)."""
    if req.menu_ids is not None:
        role = await RoleService.create_role_with_menu(req, login_user)
    else:
        role = await RoleService.create_role(req, login_user)
    _audit_log_service().create_role(login_user, get_request_ip(request), role)
    return resp_200(data={
        'id': role.id,
        'role_name': role.role_name,
        'role_type': role.role_type,
        'department_id': role.department_id,
        'quota_config': role.quota_config,
        'remark': role.remark,
        'create_time': str(role.create_time) if role.create_time else None,
    })


@router.get('', response_model=UnifiedResponseModel)
async def list_roles(
    keyword: str = Query(None, description='Filter by role_name'),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """List visible roles with pagination (AC-03, AC-04, AC-04b)."""
    result = await RoleService.list_roles(
        keyword=keyword, page=page, limit=limit, login_user=login_user,
    )
    return resp_200(data=result)


@router.get('/{role_id}', response_model=UnifiedResponseModel)
async def get_role(
    role_id: int,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Get role detail (AC-10)."""
    role = await RoleService.get_role(role_id, login_user)
    return resp_200(data=role)


@router.put('/{role_id}', response_model=UnifiedResponseModel)
async def update_role(
    request: Request,
    role_id: int,
    req: RoleUpdateRequest,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Update a role (AC-05, AC-06)."""
    if req.menu_ids is not None:
        role = await RoleService.update_role_with_menu(role_id, req, login_user)
    else:
        role = await RoleService.update_role(role_id, req, login_user)
    _audit_log_service().update_role(login_user, get_request_ip(request), role)
    return resp_200(data={
        'id': role.id,
        'role_name': role.role_name,
        'role_type': role.role_type,
        'department_id': role.department_id,
        'quota_config': role.quota_config,
        'remark': role.remark,
        'update_time': str(role.update_time) if role.update_time else None,
    })


@router.delete('/{role_id}', response_model=UnifiedResponseModel)
async def delete_role(
    request: Request,
    role_id: int,
    login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """Delete a role (AC-07, AC-08)."""
    role = await RoleService.delete_role(role_id, login_user)
    _audit_log_service().delete_role(login_user, get_request_ip(request), role)
    return resp_200(data=None)

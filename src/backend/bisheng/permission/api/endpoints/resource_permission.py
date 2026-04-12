"""Resource permission endpoints (T12b).

POST /api/v1/resources/{resource_type}/{resource_id}/authorize — Grant/revoke permissions.
GET  /api/v1/resources/{resource_type}/{resource_id}/permissions — List resource permissions.
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizeRequest,
)
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
)

router = APIRouter()


@router.post('/resources/{resource_type}/{resource_id}/authorize')
async def authorize_resource(
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Grant or revoke permissions on a resource.

    Caller must have can_manage permission on the resource.
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    # Check caller has can_manage
    from bisheng.permission.domain.services.permission_service import PermissionService
    allowed = await PermissionService.check(
        user_id=login_user.user_id,
        relation='can_manage',
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    await PermissionService.authorize(
        object_type=resource_type,
        object_id=resource_id,
        grants=request.grants,
        revokes=request.revokes,
    )
    return resp_200(None)


@router.get('/resources/{resource_type}/{resource_id}/permissions')
async def get_resource_permissions(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """List all permission entries for a resource.

    Caller must have can_manage permission on the resource.
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService
    allowed = await PermissionService.check(
        user_id=login_user.user_id,
        relation='can_manage',
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    return resp_200(permissions)

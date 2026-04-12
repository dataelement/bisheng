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
    PermissionLevel,
)
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionInvalidRelationError,
)

router = APIRouter()

# Privilege hierarchy: lower index = higher privilege
_LEVEL_ORDER = [level.value for level in PermissionLevel]  # owner, can_manage, can_edit, can_read
# Grantable role relations mapped to their required minimum level
_GRANT_RELATIONS = {'owner': 'owner', 'manager': 'can_manage', 'editor': 'can_edit', 'viewer': 'can_read'}


@router.post('/resources/{resource_type}/{resource_id}/authorize')
async def authorize_resource(
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Grant or revoke permissions on a resource.

    Caller must have can_manage permission. Non-admin callers cannot grant
    relations above their own permission level (privilege escalation guard).
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService

    # Check caller has can_manage
    allowed = await PermissionService.check(
        user_id=login_user.user_id,
        relation='can_manage',
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    # Privilege escalation guard: non-admin cannot grant 'owner'
    if not login_user.is_admin():
        caller_level = await PermissionService.get_permission_level(
            user_id=login_user.user_id,
            object_type=resource_type,
            object_id=resource_id,
        )
        caller_rank = _LEVEL_ORDER.index(caller_level) if caller_level in _LEVEL_ORDER else len(_LEVEL_ORDER)

        for grant in (request.grants or []):
            required = _GRANT_RELATIONS.get(grant.relation)
            if required and required in _LEVEL_ORDER:
                required_rank = _LEVEL_ORDER.index(required)
                if required_rank < caller_rank:
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

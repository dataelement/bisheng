"""Permission check and list endpoints (T12a).

POST /api/v1/permissions/check — Check if current user has a relation on a resource.
GET  /api/v1/permissions/objects — List accessible resource IDs.
"""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RELATIONS,
    VALID_RESOURCE_TYPES,
    PermissionCheckRequest,
)
from bisheng.common.errcode.permission import (
    PermissionInvalidResourceError,
    PermissionInvalidRelationError,
)

router = APIRouter()


@router.post('/check')
async def check_permission(
    request: PermissionCheckRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Check if current user has the given relation on a resource."""
    if request.object_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if request.relation not in VALID_RELATIONS:
        return PermissionInvalidRelationError.return_resp()

    if request.permission_id:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        allowed = await FineGrainedPermissionService.has_any_permission_async(
            login_user=login_user,
            object_type=request.object_type,
            object_id=request.object_id,
            permission_ids=[request.permission_id],
        )
        return resp_200({'allowed': allowed})

    from bisheng.permission.domain.services.permission_service import PermissionService
    allowed = await PermissionService.check(
        user_id=login_user.user_id,
        relation=request.relation,
        object_type=request.object_type,
        object_id=request.object_id,
        login_user=login_user,
    )
    return resp_200({'allowed': allowed})


@router.get('/objects')
async def list_objects(
    object_type: str = Query(..., description='Resource type'),
    relation: str = Query(default='can_read', description='Relation to check'),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """List resource IDs the current user can access.

    Returns null for admin (no filtering needed).
    Returns list of ID strings for normal users.
    """
    if object_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if relation not in VALID_RELATIONS:
        return PermissionInvalidRelationError.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService
    ids = await PermissionService.list_accessible_ids(
        user_id=login_user.user_id,
        relation=relation,
        object_type=object_type,
        login_user=login_user,
    )
    return resp_200(ids)

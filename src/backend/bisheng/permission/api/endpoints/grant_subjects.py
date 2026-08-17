"""Candidate subjects for granting permissions on one resource.

"Who may I grant this resource to" is a different question from "which users do
I administer", and it needs a different predicate: holding `manage_permission`
**on the resource**. The pickers used to ask exactly this, through
`…/resources/{type}/{id}/grant-subjects/…`; F048 (`edcbe81b`) removed those
routes and pointed both frontends at the org-management endpoints instead, so a
knowledge-space manager who administers no department or user group saw an empty
user list and a permission error on the department tree.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.permission.api.responses import permission_error_response
from bisheng.permission.application.access import get_f048_resource_registry
from bisheng.permission.application.business_authorization import check_business_action
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.permission.domain.services import grant_subject_service
from bisheng.permission.domain.services.grant_subject_service import GrantSubjectScope

router = APIRouter(tags=["Permission"])

# Every type whose permission dialog must be able to pick subjects. Five
# endpoints below each gate on this set independently, and the failure mode of
# a missing entry is not an error but an empty picker: the dialog opens and
# finds no users, no groups, and an empty department tree.
GRANT_SUBJECT_RESOURCE_TYPES = frozenset(
    {
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
        # F054 hosted applications.
        "app",
    }
)


async def _authorized_scope(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload,
) -> GrantSubjectScope:
    """Authorize the caller, then derive the candidate scope from the resource.

    The tenant comes from the verified target rather than from the caller, so a
    super admin picking subjects for another tenant's resource still sees that
    tenant's people.
    """

    actor = await resolve_permission_actor(login_user)
    registry = await get_f048_resource_registry()
    target = await registry.resolve(
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor,
        action="manage_permission",
    )
    allowed = await check_business_action(
        login_user,
        resource_type=resource_type,
        resource_id=resource_id,
        action="manage_permission",
    )
    if not allowed:
        raise PermissionDeniedError()
    return GrantSubjectScope(
        tenant_id=int(target.tenant_id),
        department_path=await grant_subject_service.resolve_department_space_path(
            resource_type,
            resource_id,
        ),
    )


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/users")
async def list_grant_subject_users(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=2000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    if resource_type not in GRANT_SUBJECT_RESOURCE_TYPES:
        return permission_error_response(PermissionDeniedError())
    try:
        scope = await _authorized_scope(resource_type, resource_id, login_user)
    except PermissionDeniedError as error:
        return permission_error_response(error)
    rows = await grant_subject_service.list_candidate_users(
        scope,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return resp_200({"data": rows, "total": len(rows)})


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/user-groups")
async def list_grant_subject_user_groups(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=2000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    if resource_type not in GRANT_SUBJECT_RESOURCE_TYPES:
        return permission_error_response(PermissionDeniedError())
    try:
        scope = await _authorized_scope(resource_type, resource_id, login_user)
    except PermissionDeniedError as error:
        return permission_error_response(error)
    rows = await grant_subject_service.list_candidate_user_groups(
        scope,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return resp_200({"data": rows, "total": len(rows)})


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/children")
async def list_grant_subject_department_children(
    resource_type: str,
    resource_id: str,
    parent_id: int | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    if resource_type not in GRANT_SUBJECT_RESOURCE_TYPES:
        return permission_error_response(PermissionDeniedError())
    try:
        scope = await _authorized_scope(resource_type, resource_id, login_user)
    except PermissionDeniedError as error:
        return permission_error_response(error)
    return resp_200(await grant_subject_service.list_candidate_department_layer(scope, parent_id=parent_id))


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/search")
async def search_grant_subject_departments(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    limit: int = Query(200, ge=1, le=1000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    if resource_type not in GRANT_SUBJECT_RESOURCE_TYPES:
        return permission_error_response(PermissionDeniedError())
    try:
        scope = await _authorized_scope(resource_type, resource_id, login_user)
    except PermissionDeniedError as error:
        return permission_error_response(error)
    return resp_200(await grant_subject_service.search_candidate_departments(scope, keyword=keyword, limit=limit))


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/{dept_id}/path-tree")
async def get_grant_subject_department_path_tree(
    resource_type: str,
    resource_id: str,
    dept_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    if resource_type not in GRANT_SUBJECT_RESOURCE_TYPES:
        return permission_error_response(PermissionDeniedError())
    try:
        scope = await _authorized_scope(resource_type, resource_id, login_user)
    except PermissionDeniedError as error:
        return permission_error_response(error)
    return resp_200(await grant_subject_service.get_candidate_department_path(scope, dept_id=dept_id))

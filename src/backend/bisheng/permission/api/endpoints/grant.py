"""F048 resource Grant, explanation, and permission-mode endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.permission.api.actors import permission_actor
from bisheng.permission.api.dependencies import (
    ResourcePermissionApiPort,
    get_resource_permission_api,
)
from bisheng.permission.api.responses import permission_error_response
from bisheng.permission.domain.schemas import (
    GrantMutationRequest,
    PermissionModeApplyRequest,
    PermissionModeDraftRequest,
)

router = APIRouter()


@router.get(
    "/resources/{resource_type}/{resource_id}/grantable-models",
    response_model=UnifiedResponseModel,
)
async def get_grantable_models(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.get_grantable_models(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.get(
    "/resources/{resource_type}/{resource_id}/context",
    response_model=UnifiedResponseModel,
)
async def get_resource_permission_context(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.get_context(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.get(
    "/resources/{resource_type}/{resource_id}/grants",
    response_model=UnifiedResponseModel,
)
async def list_resource_grants(
    resource_type: str,
    resource_id: str,
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=200),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.list_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
            cursor=cursor,
            page_size=page_size,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.get(
    "/resources/{resource_type}/{resource_id}/my-permissions",
    response_model=UnifiedResponseModel,
)
async def get_my_resource_permissions(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.get_my_permissions(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.post(
    "/resources/{resource_type}/{resource_id}/grants:mutate",
    response_model=UnifiedResponseModel,
)
async def mutate_resource_grants(
    resource_type: str,
    resource_id: str,
    body: GrantMutationRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.mutate_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
            request=body,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.post(
    "/resources/{resource_type}/{resource_id}/mode-drafts",
    response_model=UnifiedResponseModel,
)
async def create_permission_mode_draft(
    resource_type: str,
    resource_id: str,
    body: PermissionModeDraftRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.create_mode_draft(
            resource_type=resource_type,
            resource_id=resource_id,
            actor=await permission_actor(login_user),
            request=body,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.post(
    "/resources/{resource_type}/{resource_id}/mode-drafts/{draft_id}/apply",
    response_model=UnifiedResponseModel,
)
async def apply_permission_mode_draft(
    resource_type: str,
    resource_id: str,
    draft_id: str,
    body: PermissionModeApplyRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: ResourcePermissionApiPort = Depends(get_resource_permission_api),
) -> UnifiedResponseModel:
    try:
        data = await api.apply_mode_draft(
            resource_type=resource_type,
            resource_id=resource_id,
            draft_id=draft_id,
            actor=await permission_actor(login_user),
            request=body,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.get(
    "/resources/{resource_type}/{resource_id}/pending-invites",
    response_model=UnifiedResponseModel,
)
async def list_resource_pending_invites(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """People invited to this resource whose grant is still awaiting approval.

    They hold nothing yet, so they are absent from the grant list; the member
    UI shows them separately so an administrator can see an invitation is in
    flight instead of re-inviting.
    """
    from bisheng.permission.domain.services.resource_user_invite_application_service import (
        build_runtime_resource_user_invite_application_service,
    )

    try:
        service = build_runtime_resource_user_invite_application_service()
        items = await service.list_pending_invite_items(
            tenant_id=int(login_user.tenant_id),
            resource_type=resource_type,
            resource_id=resource_id,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200([item.model_dump() for item in items])


@router.post(
    "/resource-user-invites/{request_id}/retry",
    response_model=UnifiedResponseModel,
)
async def retry_resource_user_invite(
    request_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    """Re-dispatch an approved invite whose grant execution failed.

    Execution can fail on facts that have since been fixed (a stale projection,
    a transient write). Retrying re-runs the same idempotent command rather
    than asking the approver to decide again.
    """
    from bisheng.permission.domain.services.resource_user_invite_application_service import (
        build_runtime_resource_user_invite_application_service,
    )

    try:
        service = build_runtime_resource_user_invite_application_service()
        result = await service.retry_failed_invite(
            tenant_id=int(login_user.tenant_id),
            request_id=request_id,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(result.model_dump())

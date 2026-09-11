"""F048 resource Grant, explanation, and permission-mode endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import ServiceAccountOperationForbiddenError
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
        if any(change.subject is not None and change.subject.type == "service_account" for change in body.changes):
            # Service-account grants are intentionally available only from the
            # account detail management API, never the generic resource picker.
            raise ServiceAccountOperationForbiddenError()
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

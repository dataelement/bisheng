"""F048 Catalog control-plane endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.permission.api.dependencies import (
    CatalogApiPort,
    get_catalog_api,
)
from bisheng.permission.api.responses import permission_error_response
from bisheng.permission.domain.schemas import (
    CatalogDraftRequest,
    CatalogPublishRequest,
)

router = APIRouter()


def _platform_super_admin_error(
    login_user: UserPayload,
) -> UnifiedResponseModel | None:
    if bool(login_user.is_global_super):
        return None
    return PermissionDeniedError.return_resp()


@router.get("/catalog", response_model=UnifiedResponseModel)
async def get_catalog(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: CatalogApiPort = Depends(get_catalog_api),
) -> UnifiedResponseModel:
    """Return the complete current Catalog release."""

    denied = _platform_super_admin_error(login_user)
    if denied is not None:
        return denied
    try:
        data = await api.get_current()
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.post("/catalog/drafts", response_model=UnifiedResponseModel)
async def create_catalog_draft(
    body: CatalogDraftRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: CatalogApiPort = Depends(get_catalog_api),
) -> UnifiedResponseModel:
    """Build one complete server-owned draft and its impact."""

    denied = _platform_super_admin_error(login_user)
    if denied is not None:
        return denied
    try:
        data = await api.create_draft(
            request=body,
            operator_id=login_user.user_id,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.get(
    "/catalog/drafts/{draft_id}",
    response_model=UnifiedResponseModel,
)
async def get_catalog_draft(
    draft_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: CatalogApiPort = Depends(get_catalog_api),
) -> UnifiedResponseModel:
    """Return the persisted impact-bound Catalog draft."""

    denied = _platform_super_admin_error(login_user)
    if denied is not None:
        return denied
    try:
        data = await api.get_draft(
            draft_id=draft_id,
            operator_id=login_user.user_id,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)


@router.post(
    "/catalog/drafts/{draft_id}/publish",
    response_model=UnifiedResponseModel,
)
async def publish_catalog_draft(
    draft_id: int,
    body: CatalogPublishRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: CatalogApiPort = Depends(get_catalog_api),
) -> UnifiedResponseModel:
    """Publish only the named, confirmed server-side draft."""

    denied = _platform_super_admin_error(login_user)
    if denied is not None:
        return denied
    try:
        data = await api.publish_draft(
            draft_id=draft_id,
            request=body,
            operator_id=login_user.user_id,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200(data)

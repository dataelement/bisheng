"""F048 concrete-action permission decision endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import InvalidCatalogActionError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.permission.api.actors import permission_actor
from bisheng.permission.api.dependencies import (
    PermissionDecisionApiPort,
    get_permission_decision_api,
)
from bisheng.permission.api.responses import permission_error_response
from bisheng.permission.domain.schemas import PermissionCheckRequest

router = APIRouter()


@router.post("/check", response_model=UnifiedResponseModel)
async def check_permission_action(
    body: dict[str, Any],
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    api: PermissionDecisionApiPort = Depends(get_permission_decision_api),
) -> UnifiedResponseModel:
    """Check one concrete action against a business-verified target."""

    try:
        request = PermissionCheckRequest.model_validate(body)
    except ValidationError:
        return InvalidCatalogActionError.return_resp()
    try:
        actor = await permission_actor(login_user)
        if request.action == "visible" and actor.super_admin:
            # This HTTP contract answers privileged operational access. Keep the
            # domain visible Check/BatchCheck/ListObjects relation unchanged.
            return resp_200({"allowed": True})
        allowed = await api.check(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
            actor=actor,
        )
    except BaseErrorCode as error:
        return permission_error_response(error)
    return resp_200({"allowed": bool(allowed)})

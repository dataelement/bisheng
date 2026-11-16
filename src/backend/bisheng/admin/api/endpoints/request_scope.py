"""Explicit browser bootstrap and read-only scope proof for the gateway."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bisheng.admin.api.endpoints.tenant_scope import _errcode_to_response
from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.admin_scope import AdminScopeTenantRequiredError
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.request_scope import RequestScope, request_scope
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/admin/request-scope", tags=["admin-scope"])


async def _read(user, *, initialize=False):
    credential = getattr(user, "_dsh_web_session_tenant_id", None)
    if credential is not None:
        return resp_200(
            data={
                "scope_tenant_id": credential,
                "home_tenant_id": user.tenant_id,
                "user_id": user.user_id,
                "is_global_super": user.is_global_super,
                "source": "credential",
                "expires_at": None,
            }
        )
    try:
        try:
            data = await TenantScopeService.get_scope(
                user.user_id, is_super=user.is_global_super, for_write=True, require_selection=True
            )
        except AdminScopeTenantRequiredError:
            if not initialize:
                raise
            # Only this explicit bootstrap may establish a default selection.
            data = await TenantScopeService.set_scope(user.user_id, user.tenant_id)
        return resp_200(
            data={
                **data,
                "user_id": user.user_id,
                "home_tenant_id": user.tenant_id,
                "is_global_super": user.is_global_super,
            }
        )
    except BaseErrorCode as exc:
        return _errcode_to_response(exc)


@router.get("")
async def current_scope(user=Depends(UserPayload.get_login_user)):
    return await _read(user)


@router.post("/bootstrap")
async def bootstrap_scope(user=Depends(UserPayload.get_login_user)):
    return await _read(user, initialize=True)


class GatewayResource(BaseModel):
    kind: Literal["workflow", "assistant"]
    id: str = Field(min_length=1, max_length=64)


class GatewayTargets(BaseModel):
    department_id: int | None = Field(default=None, gt=0)
    resources: list[GatewayResource] = Field(default_factory=list, max_length=200)


@router.post("/resources")
@request_scope(RequestScope.TENANT)
async def gateway_targets(body: GatewayTargets, user=Depends(UserPayload.get_login_user)):
    from bisheng.admin.application.gateway_scope import authorize_gateway_targets

    return resp_200(
        data=await authorize_gateway_targets(user, department_id=body.department_id, resources=body.resources)
    )

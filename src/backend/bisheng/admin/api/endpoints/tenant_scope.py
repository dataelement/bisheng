"""Read or select one concrete management tenant; clearing is unsupported."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt

from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.admin_scope import (
    AdminScopeChangedError,
    AdminScopeForbiddenError,
    AdminScopeTenantNotFoundError,
    AdminScopeTenantRequiredError,
    AdminScopeUnavailableError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.utils.http_middleware import _check_is_global_super

router = APIRouter(prefix="/admin", tags=["admin-scope"])


# Error code → HTTP status code. Endpoint layer only; service raises the
# structured errors and we translate here.
_ERRCODE_HTTP_STATUS: dict[type[BaseErrorCode], int] = {
    AdminScopeForbiddenError: 403,
    AdminScopeTenantNotFoundError: 400,
    AdminScopeTenantRequiredError: 400,
    AdminScopeChangedError: 409,
    AdminScopeUnavailableError: 503,
}


class SetScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: StrictInt | None = None


def _errcode_to_response(exc: BaseErrorCode) -> JSONResponse:
    status_code = _ERRCODE_HTTP_STATUS.get(type(exc), 500)
    body = exc.return_resp_instance()
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump() if hasattr(body, "model_dump") else body.dict(),
    )


def _request_context(request: Request) -> dict:
    return {
        "ip": request.client.host if request.client else None,
        "ua": request.headers.get("user-agent"),
    }


@router.post("/tenant-scope")
async def set_tenant_scope(
    body: SetScopeRequest,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Select an active concrete tenant without changing identity membership."""
    if not await _check_is_global_super(user.user_id):
        return _errcode_to_response(AdminScopeForbiddenError())

    try:
        result = await TenantScopeService.set_scope(
            user_id=user.user_id,
            tenant_id=body.tenant_id,
            request_context=_request_context(request),
        )
    except BaseErrorCode as exc:
        return _errcode_to_response(exc)
    return resp_200(data=result)


@router.get("/tenant-scope")
async def get_tenant_scope(
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the caller's current scope + ISO expiry."""
    if not await _check_is_global_super(user.user_id):
        return _errcode_to_response(AdminScopeForbiddenError())

    data = await TenantScopeService.get_scope(user_id=user.user_id, is_super=True)
    return resp_200(data=data)

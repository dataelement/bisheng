"""F019-admin-tenant-scope HTTP endpoints.

Routes:

  POST  /api/v1/admin/tenant-scope   — set/clear the caller's scope
  GET   /api/v1/admin/tenant-scope   — read current scope + remaining TTL

Only the global super admin may use these endpoints. Child Admins and
ordinary users receive HTTP 403 + structured code 19701
(``admin_scope_forbidden``). Unknown target tenant ids receive HTTP 400 +
19702 (``admin_scope_tenant_not_found``).

The endpoint layer is a thin wrapper over ``TenantScopeService``; all the
Redis / audit_log effects live in the service. Error translation follows
F018's precedent (``_errcode_to_response``): we return genuine HTTP 403/
400 with the structured body carrying the 5-digit ``status_code``.

**is_global_super detection**: F013's ``LoginUser.is_global_super()``
public method was not shipped; we reuse the module-private helper the
request middleware uses (``_check_is_global_super``) so the decision
matches everywhere else in the stack — same FGA query, same Redis cache.
"""

from __future__ import annotations

from typing import Optional, Type

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.admin_scope import (
    AdminScopeForbiddenError,
    AdminScopeTenantNotFoundError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.utils.http_middleware import _check_is_global_super

router = APIRouter(prefix='/admin', tags=['admin-scope'])


# Error code → HTTP status code. Endpoint layer only; service raises the
# structured errors and we translate here.
_ERRCODE_HTTP_STATUS: dict[Type[BaseErrorCode], int] = {
    AdminScopeForbiddenError: 403,
    AdminScopeTenantNotFoundError: 400,
}


class SetScopeRequest(BaseModel):
    tenant_id: Optional[int] = None


class ScopeResponse(BaseModel):
    scope_tenant_id: Optional[int] = None
    expires_at: Optional[str] = None


def _errcode_to_response(exc: BaseErrorCode) -> JSONResponse:
    status_code = _ERRCODE_HTTP_STATUS.get(type(exc), 500)
    body = exc.return_resp_instance()
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump() if hasattr(body, 'model_dump') else body.dict(),
    )


def _request_context(request: Request) -> dict:
    return {
        'ip': request.client.host if request.client else None,
        'ua': request.headers.get('user-agent'),
    }


@router.post('/tenant-scope')
async def set_tenant_scope(
    body: SetScopeRequest,
    request: Request,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Set or clear the caller's admin tenant-scope.

    Body: ``{tenant_id: int | null}``. Passing ``null`` clears the Redis
    key. Non-super callers are rejected before any side effect.
    """
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


@router.get('/tenant-scope')
async def get_tenant_scope(
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the caller's current scope + ISO expiry."""
    if not await _check_is_global_super(user.user_id):
        return _errcode_to_response(AdminScopeForbiddenError())

    data = await TenantScopeService.get_scope(user_id=user.user_id)
    return resp_200(data=data)

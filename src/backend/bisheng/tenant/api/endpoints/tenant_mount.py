"""F011 tenant mount / unmount / resource-migrate HTTP endpoints.

Routes exposed (all mounted under the tenant module router):

  POST   /api/v1/departments/{dept_id}/mount-tenant
  DELETE /api/v1/departments/{dept_id}/mount-tenant
  POST   /api/v1/tenants/{child_id}/resources/migrate-from-root

Handlers are thin — the real logic lives in ``TenantMountService``. The
adapter layer only handles auth injection, request-body validation,
and mapping ``BaseErrorCode`` subclasses to HTTP status codes that the
frontend / gateway can short-circuit on (403 for super-admin gate, 400
for spec-level structural errors).
"""

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.tenant_tree import (
    TenantTreeMigrateConflictError,
    TenantTreeMigratePermissionError,
    TenantTreeMountConflictError,
    TenantTreeNestingForbiddenError,
    TenantTreeRootDeptMountError,
    TenantTreeRootProtectedError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import (
    MigrateFromRootRequest,
    MountTenantRequest,
    UnmountTenantRequest,
)
from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

router = APIRouter()


# ---------------------------------------------------------------------------
# HTTP status mapping: F011 error codes → HTTP
# ---------------------------------------------------------------------------

_HTTP_400 = {
    TenantTreeNestingForbiddenError,
    TenantTreeMountConflictError,
    TenantTreeMigrateConflictError,
    TenantTreeRootDeptMountError,
}
_HTTP_403 = {
    TenantTreeMigratePermissionError,
    TenantTreeRootProtectedError,
}


def _errcode_to_response(exc: BaseErrorCode) -> JSONResponse:
    """Translate the error into (http_status, UnifiedResponseModel)."""
    resp = exc.return_resp_instance()
    # Default: 500. F011 bucketing per spec §9 + AC-03/AC-10/AC-11/AC-15.
    if type(exc) in _HTTP_403:
        status_code = 403
    elif type(exc) in _HTTP_400:
        status_code = 400
    else:
        status_code = 500
    # ``return_resp_instance`` returns a pydantic model — jsonable.
    return JSONResponse(
        status_code=status_code, content=resp.model_dump(mode='json'),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post('/departments/{dept_id}/mount-tenant')
async def mount_tenant(
    dept_id: int,
    data: MountTenantRequest,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        tenant = await TenantMountService.mount_child(
            dept_id=dept_id,
            tenant_code=data.tenant_code,
            tenant_name=data.tenant_name,
            operator=login_user,
        )
        # Explicit field projection — Tenant is a dataclass-like ORM and
        # these fields are always populated after a successful INSERT.
        payload = {
            'id': tenant.id,
            'tenant_code': tenant.tenant_code,
            'tenant_name': tenant.tenant_name,
            'parent_tenant_id': tenant.parent_tenant_id,
            'status': tenant.status,
        }
        return resp_200(payload)
    except BaseErrorCode as e:
        return _errcode_to_response(e)


@router.delete('/departments/{dept_id}/mount-tenant')
async def unmount_tenant(
    dept_id: int,
    data: Optional[UnmountTenantRequest] = None,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """v2.5.1 收窄到唯一路径：资源迁回 Root + Child 归档。

    Body 字段保留以兼容旧客户端（任何 policy 值都走 migrate 行为）。
    """
    _ = data  # accepted for backwards compatibility, ignored
    try:
        result = await TenantMountService.unmount_child(
            dept_id=dept_id,
            operator=login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return _errcode_to_response(e)


@router.post('/tenants/{child_id}/resources/migrate-from-root')
async def migrate_from_root(
    child_id: int,
    data: MigrateFromRootRequest,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    try:
        result = await TenantMountService.migrate_resources_from_root(
            child_id=child_id,
            resource_type=data.resource_type,
            resource_ids=data.resource_ids,
            operator=login_user,
            new_owner_user_id=data.new_owner_user_id,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return _errcode_to_response(e)

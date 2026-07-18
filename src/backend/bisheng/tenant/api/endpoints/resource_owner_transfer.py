"""F018 resource-owner-transfer HTTP endpoints.

Routes (mounted under the tenant module router):

  POST  /api/v1/tenants/{tenant_id}/resources/transfer-owner
  GET   /api/v1/tenants/{tenant_id}/resources/pending-transfer

The handlers are thin wrappers over
``ResourceOwnershipService.transfer_owner`` / ``.list_pending_transfer``.
Auth is injected as the generic login user — the service itself enforces
the three-way gate (owner / tenant admin / global super) described by
spec AC-03; the endpoint only refuses outright unauthenticated requests.

Error translation follows the F011 precedent: ``BaseErrorCode`` subclasses
raised by the service are mapped to HTTP status codes (400 for spec-level
structural errors, 403 for permission gates, 500 as fallback).
"""

from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferBatchLimitError,
    ResourceTransferPermissionError,
    ResourceTransferReceiverOutOfTenantError,
    ResourceTransferSelfError,
    ResourceTransferTxFailedError,
    ResourceTransferUnsupportedTypeError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.tenant.domain.schemas.tenant_schema import (
    PendingTransferItem,
    TransferOwnerRequest,
    TransferOwnerResponse,
)
from bisheng.tenant.domain.services.resource_ownership_service import (
    ResourceOwnershipService,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Error code → HTTP status mapping
# ---------------------------------------------------------------------------

# 400 — structural request issues. Includes AC-07 (batch > 500), AC-08
# (receiver out of visible set), unsupported type, and self-transfer.
_HTTP_400 = {
    ResourceTransferBatchLimitError,
    ResourceTransferReceiverOutOfTenantError,
    ResourceTransferUnsupportedTypeError,
    ResourceTransferSelfError,
}
# 403 — permission gate (AC-03).
_HTTP_403 = {
    ResourceTransferPermissionError,
}
# 500 — transaction failure (AC-06). Response body carries the structured
# 19605 code so the caller can distinguish from unhandled errors.
_HTTP_500 = {
    ResourceTransferTxFailedError,
}


def _errcode_to_response(exc: BaseErrorCode) -> JSONResponse:
    resp = exc.return_resp_instance()
    if type(exc) in _HTTP_403:
        status_code = 403
    elif type(exc) in _HTTP_400:
        status_code = 400
    elif type(exc) in _HTTP_500:
        status_code = 500
    else:
        status_code = 500
    return JSONResponse(
        status_code=status_code, content=resp.model_dump(mode='json'),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post('/tenants/{tenant_id}/resources/transfer-owner')
async def transfer_owner(
    tenant_id: int,
    data: TransferOwnerRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await ResourceOwnershipService.transfer_owner(
            tenant_id=tenant_id,
            from_user_id=data.from_user_id,
            to_user_id=data.to_user_id,
            resource_types=list(data.resource_types),
            resource_ids=data.resource_ids,
            reason=data.reason,
            operator=login_user,
        )
        return resp_200(TransferOwnerResponse(**result))
    except BaseErrorCode as exc:
        return _errcode_to_response(exc)


@router.get('/tenants/{tenant_id}/resources/pending-transfer')
async def list_pending_transfer(
    tenant_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    # Only tenant admins / global supers may enumerate pending transfers
    # — this list can reveal relocated/ex-employee user ids, so it's not a
    # public listing. Owner-self cannot use this endpoint.
    is_super = getattr(login_user, 'is_global_super', None)
    is_admin = getattr(login_user, 'is_admin', None)
    has_super = callable(is_super) and is_super()
    has_admin = callable(is_admin) and is_admin()
    if not (has_super or has_admin):
        return _errcode_to_response(ResourceTransferPermissionError())
    try:
        items = await ResourceOwnershipService.list_pending_transfer(
            tenant_id=tenant_id,
        )
        return resp_200([PendingTransferItem(**it) for it in items])
    except BaseErrorCode as exc:
        return _errcode_to_response(exc)

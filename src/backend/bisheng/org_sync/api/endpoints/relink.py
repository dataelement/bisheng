"""F015 department relink endpoints.

Two HMAC-authenticated POST routes, mounted at:

- ``POST /api/v1/internal/departments/relink``
- ``POST /api/v1/internal/departments/relink/resolve-conflict``

Both bypass the tenant-context middleware (listed in
``TENANT_CHECK_EXEMPT_PATHS``) and rely on :func:`verify_hmac` from
F014 — the Gateway signs each call with the shared secret. The
underlying service layer runs under ROOT_TENANT_ID implicitly via the
DAO helpers.
"""

from fastapi import APIRouter, Depends, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.org_sync.domain.schemas.relink import (
    RelinkAppliedItem,
    RelinkRequest,
    RelinkResponse,
    ResolveConflictRequest,
)
from bisheng.org_sync.domain.services.relink_service import (
    DepartmentRelinkService,
)
from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac


router = APIRouter(tags=['F015 Relink'])


@router.post(
    '/internal/departments/relink',
    response_model=UnifiedResponseModel[RelinkResponse],
    summary='SSO migration relink (external_id_map | path_plus_name)',
)
async def relink(
    payload: RelinkRequest,
    request: Request,
    _: None = Depends(verify_hmac),
):
    """Relink existing depts to new external_ids after an SSO migration."""
    result = await DepartmentRelinkService.relink(payload)
    return resp_200(result)


@router.post(
    '/internal/departments/relink/resolve-conflict',
    response_model=UnifiedResponseModel[RelinkAppliedItem],
    summary='Manually resolve a multi-candidate relink conflict',
)
async def resolve_conflict(
    payload: ResolveConflictRequest,
    request: Request,
    _: None = Depends(verify_hmac),
):
    """Apply the operator's chosen ``new_external_id`` from the
    conflict store and delete the entry."""
    result = await DepartmentRelinkService.resolve_conflict(
        dept_id=payload.dept_id,
        chosen_new_external_id=payload.chosen_new_external_id,
    )
    return resp_200(result)

"""SG organization sync endpoint."""

from fastapi import APIRouter, Depends

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDepartmentSyncRequest,
)
from bisheng.sso_sync.domain.services.sg_fixed_header_auth import (
    verify_sg_fixed_header,
)
from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
    SgDepartmentsSyncService,
)

router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/departments/sg-sync',
    summary='SG bulk department sync (HMAC-signed)',
)
async def sg_departments_sync(
    payload: SgDepartmentSyncRequest,
    _: None = Depends(verify_sg_fixed_header),
):
    """SG callback with ESB-shaped response body."""
    result = await SgDepartmentsSyncService.execute(payload)
    return result.model_dump(by_alias=True)


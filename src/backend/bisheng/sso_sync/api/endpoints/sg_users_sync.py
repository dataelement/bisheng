"""SG user sync endpoint."""

from fastapi import APIRouter, Depends

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgUserSyncRequest,
)
from bisheng.sso_sync.domain.services.sg_fixed_header_auth import (
    verify_sg_fixed_header,
)
from bisheng.sso_sync.domain.services.sg_users_sync_service import (
    SgUsersSyncService,
)

router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/users/sg-sync',
    summary='SG bulk user sync (HMAC-signed)',
)
async def sg_users_sync(
    payload: SgUserSyncRequest,
    _: None = Depends(verify_sg_fixed_header),
):
    """SG callback with ESB-shaped response body for users."""
    result = await SgUsersSyncService.execute(payload)
    return result.model_dump(by_alias=True)


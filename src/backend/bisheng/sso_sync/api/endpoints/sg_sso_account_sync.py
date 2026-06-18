"""SG SSO account info sync endpoint."""

from fastapi import APIRouter, Depends

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgSsoAccountSyncRequest,
)
from bisheng.sso_sync.domain.services.sg_fixed_header_auth import (
    verify_sg_fixed_header,
)
from bisheng.sso_sync.domain.services.sg_sso_account_sync_service import (
    SgSsoAccountSyncService,
)

router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/users/sg-sso-sync',
    summary='SG SSO account info sync (HMAC-signed)',
)
async def sg_sso_account_sync(
    payload: SgSsoAccountSyncRequest,
    _: None = Depends(verify_sg_fixed_header),
):
    """Sync SG SSO account fields to user table."""
    result = await SgSsoAccountSyncService.execute(payload)
    return result.model_dump(by_alias=True)


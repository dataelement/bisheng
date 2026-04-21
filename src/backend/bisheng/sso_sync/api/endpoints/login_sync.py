"""F014 ``POST /api/v1/internal/sso/login-sync`` endpoint."""

from fastapi import APIRouter, Depends, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.sso_sync.domain.schemas.payloads import (
    LoginSyncRequest,
    LoginSyncResponse,
)
from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac
from bisheng.sso_sync.domain.services.login_sync_service import (
    LoginSyncService,
)
from bisheng.sso_sync.domain.services.org_sync_log_writer import (
    OrgSyncLogBuffer,
    flush_log,
)
from bisheng.utils import get_request_ip


router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/internal/sso/login-sync',
    response_model=UnifiedResponseModel[LoginSyncResponse],
    summary='Gateway SSO login sync (HMAC-signed)',
)
async def login_sync(
    payload: LoginSyncRequest,
    request: Request,
    _: None = Depends(verify_hmac),
):
    """HMAC-signed login callback from the Gateway. Upserts user + primary/
    secondary departments, derives the leaf tenant via F012 sync, and
    returns a freshly signed JWT.
    """
    buffer = OrgSyncLogBuffer()
    result = await LoginSyncService.execute(
        payload, request_ip=get_request_ip(request),
    )
    # Best-effort per-request audit row. Keeping log writes here (rather
    # than inside the service) means service-level unit tests don't need
    # to patch OrgSyncLogDao.
    buffer.member_updated += 1
    await flush_log(buffer, trigger_type='sso_realtime')
    return resp_200(result)

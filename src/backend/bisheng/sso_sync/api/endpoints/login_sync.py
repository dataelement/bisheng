"""F014 ``POST /api/v1/internal/sso/login-sync`` endpoint."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.sso_sync.domain.constants import DEFAULT_SSO_SYNC_SOURCE
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
    try:
        result = await LoginSyncService.execute(
            payload,
            request_ip=get_request_ip(request),
            row_source=payload.source or DEFAULT_SSO_SYNC_SOURCE,
        )
    except BaseErrorCode as exc:
        return JSONResponse(
            content=UnifiedResponseModel(
                status_code=exc.code,
                status_message=exc.message,
                data=None,
            ).model_dump(mode='json'),
        )
    # Best-effort per-request audit row. ``skip_org_sync_log`` is used when
    # Gateway calls ``gateway_wecom_org_sync`` which flushes a single row.
    if not payload.skip_org_sync_log:
        buffer = OrgSyncLogBuffer()
        buffer.member_updated += 1
        await flush_log(buffer, trigger_type='sso_realtime')
    return resp_200(result)

"""F014 Gateway WeCom org push: departments + members in one ``org_sync_log`` row.

Application logic lives in
``bisheng.sso_sync.domain.services.wecom_org_sync_service``; the admin console's
"run now" task reuses it, so both entry points write identical state and logs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.sso_sync.domain.schemas.payloads import (
    GatewayWecomOrgSyncRequest,
    GatewayWecomOrgSyncResult,
)
from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac
from bisheng.sso_sync.domain.services.wecom_org_sync_service import (
    apply_wecom_org_snapshot,
)
from bisheng.utils import get_request_ip

router = APIRouter(tags=["SSO Sync"])


@router.post(
    "/internal/sso/gateway-wecom-org-sync",
    response_model=UnifiedResponseModel[GatewayWecomOrgSyncResult],
    summary="Gateway WeCom org push (departments + members, single org_sync_log)",
)
async def gateway_wecom_org_sync(
    payload: GatewayWecomOrgSyncRequest,
    request: Request,
    _: None = Depends(verify_hmac),
):
    """Runs :class:`DepartmentsSyncService` then each member ``LoginSyncService``
    with ``skip_org_sync_log=True``, and flushes **one** ``org_sync_log`` row
    aggregating department + member counters (end_time = wall clock end).
    """
    result = await apply_wecom_org_snapshot(
        payload,
        request_ip=get_request_ip(request),
        # The signed body may label the run: the Gateway omits it
        # (sso_realtime), the no-Gateway cron script sends "scheduled".
        trigger_type=payload.trigger_type or "sso_realtime",
    )
    return resp_200(result)

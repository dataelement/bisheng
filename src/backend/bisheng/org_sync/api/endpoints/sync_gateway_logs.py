"""Read-only listing of gateway org sync log rows (F014 ``sso_realtime``)."""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.org_sync.domain.models.org_sync import OrgSyncLogDao
from bisheng.org_sync.domain.schemas.org_sync_schema import OrgSyncLogRead

router = APIRouter()


@router.get('/gateway-logs')
async def list_gateway_sync_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    _: UserPayload = Depends(UserPayload.get_admin_user),
):
    """List ``org_sync_log`` rows produced by HMAC gateway sync (``sso_realtime``)."""
    try:
        logs, total = await OrgSyncLogDao.aget_gateway_sso_logs(page, limit)
        log_reads = [
            OrgSyncLogRead.model_validate(log).model_dump(mode='json')
            for log in logs
        ]
        return resp_200(PageData(data=log_reads, total=total).model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()

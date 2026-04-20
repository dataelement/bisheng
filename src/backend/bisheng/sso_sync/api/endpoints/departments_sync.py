"""F014 ``POST /api/v1/departments/sync`` endpoint."""

from fastapi import APIRouter, Depends, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.sso_sync.domain.schemas.payloads import (
    BatchResult,
    DepartmentsSyncRequest,
)
from bisheng.sso_sync.domain.services.departments_sync_service import (
    DepartmentsSyncService,
)
from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac
from bisheng.sso_sync.domain.services.org_sync_log_writer import (
    OrgSyncLogBuffer,
    flush_log,
)
from bisheng.utils import get_request_ip


router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/departments/sync',
    response_model=UnifiedResponseModel[BatchResult],
    summary='Bulk Gateway department push (HMAC-signed)',
)
async def departments_sync(
    payload: DepartmentsSyncRequest,
    request: Request,
    _: None = Depends(verify_hmac),
):
    """HMAC-signed batch department sync. Runs upsert + remove rounds,
    per-item isolated (AC-11), and returns the aggregated summary.
    """
    result = await DepartmentsSyncService.execute(
        payload, request_ip=get_request_ip(request),
    )
    # Single summary row in ``org_sync_log`` per request.
    buffer = OrgSyncLogBuffer(
        dept_updated=result.applied_upsert,
        dept_archived=result.applied_remove,
    )
    for err in result.errors:
        buffer.error(
            err.get('type', 'unknown'),
            err.get('external_id', ''),
            err.get('error', ''),
        )
    status = 'partial' if (
        result.errors or result.skipped_ts_conflict > 0
    ) else 'success'
    await flush_log(buffer, trigger_type='sso_realtime', status=status)
    return resp_200(result)

"""F014 Gateway 单次企微组织推送：部门 + 多成员，合并一条 ``org_sync_log``。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.sso_sync.domain.schemas.payloads import (
    GatewayWecomOrgSyncRequest,
    GatewayWecomOrgSyncResult,
)
from bisheng.sso_sync.domain.services.departments_sync_service import (
    DepartmentsSyncService,
)
from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac
from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService
from bisheng.sso_sync.domain.services.org_sync_log_writer import (
    OrgSyncLogBuffer,
    flush_log,
)
from bisheng.utils import get_request_ip

router = APIRouter(tags=['SSO Sync'])


@router.post(
    '/internal/sso/gateway-wecom-org-sync',
    response_model=UnifiedResponseModel[GatewayWecomOrgSyncResult],
    summary='Gateway WeCom org push (departments + members, single org_sync_log)',
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
    request_ip = get_request_ip(request)
    buffer = OrgSyncLogBuffer()

    dept_result = await DepartmentsSyncService.execute(
        payload.departments, request_ip=request_ip,
    )
    buffer.dept_updated = dept_result.applied_upsert
    buffer.dept_archived = dept_result.applied_remove
    for err in dept_result.errors:
        buffer.error(
            err.get('type', 'unknown'),
            err.get('external_id', ''),
            err.get('error', ''),
        )

    member_ok = 0
    member_fail = 0
    member_errors: list[dict] = []
    members_with_leader_depts = 0
    for raw in payload.members:
        item = raw.model_copy(update={'skip_org_sync_log': True})
        try:
            await LoginSyncService.execute(item, request_ip=request_ip)
            member_ok += 1
        except Exception as e:  # noqa: BLE001 — aggregate per-user failures
            member_fail += 1
            msg = str(e)
            if len(member_errors) < 50:
                member_errors.append({
                    'external_user_id': item.external_user_id,
                    'error': msg,
                })
            buffer.error('member', item.external_user_id, msg)
        else:
            admins = item.department_admin_external_ids or []
            if admins:
                members_with_leader_depts += 1

    buffer.member_updated = member_ok
    buffer.warn(
        'gateway_batch_summary',
        '',
        members_sync_ok=member_ok,
        members_sync_fail=member_fail,
        members_with_leader_depts=members_with_leader_depts,
        dept_upsert_applied=dept_result.applied_upsert,
        dept_remove_applied=dept_result.applied_remove,
    )
    status = 'partial' if (
        dept_result.errors
        or dept_result.skipped_ts_conflict > 0
        or member_fail
        or buffer.errors
    ) else 'success'
    await flush_log(buffer, trigger_type='sso_realtime', status=status)

    out = GatewayWecomOrgSyncResult(
        department_result=dept_result,
        member_sync_ok=member_ok,
        member_sync_fail=member_fail,
        member_errors=member_errors,
    )
    return resp_200(out)

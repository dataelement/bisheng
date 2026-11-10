"""Apply a Gateway-shaped WeCom org snapshot (departments + members).

One implementation, two callers:

- ``POST /api/v1/internal/sso/gateway-wecom-org-sync`` — the commercial
  Gateway (or the no-Gateway sync script) pushes a signed payload;
- the admin console's "run now" task (``pull_sync_service``) builds the same
  payload in-process from ``WeComProvider``.

Both therefore write identical state and one ``org_sync_log`` row per run.
A run that raises still gets a ``failed`` row, so the 组织同步 page shows the
attempt instead of going silent.
"""

from __future__ import annotations

from loguru import logger

from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.sso_sync.domain.schemas.payloads import (
    DepartmentsSyncRequest,
    GatewayWecomOrgSyncRequest,
    GatewayWecomOrgSyncResult,
    LoginSyncRequest,
)
from bisheng.sso_sync.domain.services.departments_sync_service import DepartmentsSyncService
from bisheng.sso_sync.domain.services.login_sync_service import LoginSyncService
from bisheng.sso_sync.domain.services.org_sync_log_writer import OrgSyncLogBuffer, flush_log
from bisheng.sso_sync.domain.services.wecom_gateway_absent_reconcile import (
    disable_wecom_users_absent_from_import,
)


def _merge_member_department_ids_into_snapshot(
    departments: DepartmentsSyncRequest,
    members: list[LoginSyncRequest],
) -> DepartmentsSyncRequest:
    """Ensure primary/secondary dept ids from synced members stay in the flat snapshot.

    Defensive: empty-middle departments with no members would not appear here, but
    any dept still referenced by an included member cannot be absent-reconciled away.
    """
    refs: set[str] = set()
    for member in members:
        if member.primary_dept_external_id:
            value = str(member.primary_dept_external_id).strip()
            if value:
                refs.add(value)
        for secondary in member.secondary_dept_external_ids or []:
            if not secondary:
                continue
            value = str(secondary).strip()
            if value:
                refs.add(value)
    if not refs:
        return departments
    snapshot = list(departments.snapshot_external_ids or [])
    known = {str(x).strip() for x in snapshot if x is not None and str(x).strip()}
    for ref in refs:
        if ref not in known:
            snapshot.append(ref)
            known.add(ref)
    return departments.model_copy(update={"snapshot_external_ids": snapshot})


async def apply_wecom_org_snapshot(
    payload: GatewayWecomOrgSyncRequest,
    *,
    request_ip: str,
    trigger_type: str = "sso_realtime",
    config_id: int | None = None,
    trigger_user: int | None = None,
) -> GatewayWecomOrgSyncResult:
    """Apply one snapshot and always leave an ``org_sync_log`` row behind.

    Success/partial rows are written by the run itself; an exception writes a
    ``failed`` row (error details attached) and is then re-raised so the caller
    still sees the failure.
    """
    try:
        return await _apply_snapshot(
            payload,
            request_ip=request_ip,
            trigger_type=trigger_type,
            config_id=config_id,
            trigger_user=trigger_user,
        )
    except Exception as exc:
        logger.exception(
            "org sync run failed (trigger={}, config_id={})",
            trigger_type,
            config_id,
        )
        buffer = OrgSyncLogBuffer()
        buffer.error("run", "", str(exc))
        await flush_log(
            buffer,
            trigger_type=trigger_type,
            status="failed",
            config_id=config_id,
            trigger_user=trigger_user,
        )
        raise


async def _apply_snapshot(
    payload: GatewayWecomOrgSyncRequest,
    *,
    request_ip: str,
    trigger_type: str,
    config_id: int | None,
    trigger_user: int | None,
) -> GatewayWecomOrgSyncResult:
    buffer = OrgSyncLogBuffer()

    # Honour the caller's ``full_snapshot`` flag so a Gateway pushing in
    # batches can send incremental envelopes (full_snapshot=false) for the
    # leading batches and a final authoritative envelope (full_snapshot=true
    # with full ``snapshot_external_ids`` + full ``members``) to trigger
    # department and user absent reconcile only on the last batch.
    dept_payload = _merge_member_department_ids_into_snapshot(
        payload.departments,
        payload.members,
    )
    dept_result = await DepartmentsSyncService.execute(
        dept_payload,
        request_ip=request_ip,
        row_source=WECOM_SOURCE,
    )
    buffer.dept_updated = dept_result.applied_upsert
    buffer.dept_archived = dept_result.applied_remove
    for err in dept_result.errors:
        buffer.error(
            err.get("type", "unknown"),
            err.get("external_id", ""),
            err.get("error", ""),
        )

    member_ok, member_fail, member_errors, members_with_leader_depts = await _sync_members(
        payload.members,
        request_ip=request_ip,
        buffer=buffer,
    )

    # PRD: 第三方同步人员不在本次导入名单中 → 已禁用 + 强退。
    # Only the authoritative batch (full_snapshot=true) carries the complete
    # member roster; incremental batches must skip this reconcile or they'd
    # disable every user not in the current chunk.
    absent_disabled = 0
    if payload.departments.full_snapshot:
        seen_external = {
            str(m.external_user_id).strip()
            for m in payload.members
            if m.external_user_id and str(m.external_user_id).strip()
        }
        try:
            absent_disabled = await disable_wecom_users_absent_from_import(seen_external)
        except Exception as e:
            buffer.error("absent_reconcile", "", str(e))

    buffer.member_updated = member_ok
    buffer.warn(
        "gateway_batch_summary",
        "",
        members_sync_ok=member_ok,
        members_sync_fail=member_fail,
        members_with_leader_depts=members_with_leader_depts,
        dept_upsert_applied=dept_result.applied_upsert,
        dept_remove_applied=dept_result.applied_remove,
    )
    status = (
        "partial"
        if (dept_result.errors or dept_result.skipped_ts_conflict > 0 or member_fail or buffer.errors)
        else "success"
    )
    await flush_log(
        buffer,
        trigger_type=trigger_type,
        status=status,
        config_id=config_id,
        trigger_user=trigger_user,
    )

    return GatewayWecomOrgSyncResult(
        department_result=dept_result,
        member_sync_ok=member_ok,
        member_sync_fail=member_fail,
        member_errors=member_errors,
        absent_wecom_users_disabled=absent_disabled,
    )


async def _sync_members(
    members: list[LoginSyncRequest],
    *,
    request_ip: str,
    buffer: OrgSyncLogBuffer,
) -> tuple[int, int, list[dict], int]:
    """Login-sync each member; per-user failures are aggregated, never raised.

    Returns ``(ok, fail, errors, members_with_leader_depts)``.
    """
    member_ok = 0
    member_fail = 0
    member_errors: list[dict] = []
    members_with_leader_depts = 0
    for raw in members:
        # Gateway WeCom org sync is an authoritative full member snapshot.
        # Older gateway builds omitted this field when a user had no secondary
        # departments; normalize it to [] so stale WeCom secondary memberships
        # are removed instead of preserved by legacy login-sync compatibility.
        item = raw.model_copy(
            update={
                "secondary_dept_external_ids": raw.secondary_dept_external_ids or [],
                "skip_org_sync_log": True,
            }
        )
        try:
            await LoginSyncService.execute(
                item,
                request_ip=request_ip,
                row_source=WECOM_SOURCE,
            )
            member_ok += 1
        except Exception as e:
            member_fail += 1
            msg = str(e)
            if len(member_errors) < 50:
                member_errors.append(
                    {
                        "external_user_id": item.external_user_id,
                        "error": msg,
                    }
                )
            buffer.error("member", item.external_user_id, msg)
        else:
            admins = item.department_admin_external_ids or []
            if admins:
                members_with_leader_depts += 1
    return member_ok, member_fail, member_errors, members_with_leader_depts

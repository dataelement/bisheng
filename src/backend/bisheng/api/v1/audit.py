from datetime import datetime

from fastapi import APIRouter, Depends, Query

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload

router = APIRouter(prefix="/audit", tags=["AuditLog"])


@router.get("")
async def get_audit_logs(
    *,
    group_ids: list[str] | None = Query(default=[], description="GroupingidVertical"),
    operator_ids: list[int] | None = Query(default=[], description="WhoidVertical"),
    start_time: datetime | None = Query(default=None, description="Start when"),
    end_time: datetime | None = Query(default=None, description="End time"),
    system_id: str | None = Query(default=None, description="Module Item"),
    event_type: str | None = Query(default=None, description="Operation behaviors"),
    target_app_id: str | None = Query(default=None, description="F056: only rows about this hosted application"),
    tenant_id: int | None = Query(
        default=None, description="F056: narrow to one tenant (global super only; others must match their own)"
    ),
    page: int | None = Query(default=0, description="Page"),
    limit: int | None = Query(default=0, description="Listings Per Page"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    group_ids = [one for one in group_ids if one]
    operator_ids = [one for one in operator_ids if one]
    return await AuditLogService.get_audit_log(
        login_user,
        group_ids,
        operator_ids,
        start_time,
        end_time,
        system_id,
        event_type,
        page,
        limit,
        target_app_id=target_app_id or None,
        tenant_id=tenant_id,
    )


@router.get("/apps")
async def search_audit_apps(
    *,
    keyword: str | None = Query(default="", description="Name or slug substring"),
    limit: int = Query(default=20, ge=1, le=50),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Options for the audit page's object-application selector (F056 AC-28).

    Deleted applications are included so their events stay reachable.
    """
    return resp_200(data=await AuditLogService.search_audit_apps(login_user, keyword or "", limit))


@router.get("/export/data")
async def export_audit_logs(
    *,
    group_ids: list[str] | None = Query(default=[], description="GroupingidVertical"),
    operator_ids: list[int] | None = Query(default=[], description="WhoidVertical"),
    start_time: datetime | None = Query(default=None, description="Start when"),
    end_time: datetime | None = Query(default=None, description="End time"),
    system_id: str | None = Query(default=None, description="Module Item"),
    event_type: str | None = Query(default=None, description="Operation behaviors"),
    target_app_id: str | None = Query(default=None),
    tenant_id: int | None = Query(default=None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Rows for the system-audit export (F056 AC-32) — same filters, same
    tenant / role boundary as the list. ``total`` is the query's full count so
    the caller can tell when the capped ``data`` is incomplete.
    """
    group_ids = [one for one in group_ids if one]
    operator_ids = [one for one in operator_ids if one]
    rows, total = await AuditLogService.export_audit_log(
        login_user,
        group_ids,
        operator_ids,
        start_time,
        end_time,
        system_id,
        event_type,
        target_app_id=target_app_id or None,
        tenant_id=tenant_id,
    )
    return resp_200(data={"data": rows, "total": total})


@router.get("/operators")
async def get_all_operators(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get all users who have acted on a resource under a group
    """
    return resp_200(data=await AuditLogService.get_all_operators(login_user))


@router.get("/session")
async def get_session_list(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    flow_ids: list[str] | None = Query(default=[], description="ApplicationsidVertical"),
    user_ids: list[int] | None = Query(default=[], description="UsersidVertical"),
    group_ids: list[int] | None = Query(default=[], description="User GroupsidVertical"),
    start_date: datetime | None = Query(default=None, description="Start when"),
    end_date: datetime | None = Query(default=None, description="End time"),
    feedback: str | None = Query(default=None, description="like LikedislikeUnlikecopiedCopy:"),
    sensitive_status: int | None = Query(default=None, description="Sensitive word review status"),
    page: int | None = Query(default=1, description="Page"),
    page_size: int | None = Query(default=10, description="Listings Per Page"),
):
    """Filter all session lists"""
    data, total = await AuditLogService.get_session_list(
        login_user, flow_ids, user_ids, group_ids, start_date, end_date, feedback, sensitive_status, page, page_size
    )
    return resp_200(data={"data": data, "total": total})


@router.get("/session/export/data")
async def get_session_messages(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    flow_ids: list[str] | None = Query(default=[], description="ApplicationsidVertical"),
    user_ids: list[int] | None = Query(default=[], description="UsersidVertical"),
    group_ids: list[int] | None = Query(default=[], description="User GroupsidVertical"),
    start_date: datetime | None = Query(default=None, description="Start when"),
    end_date: datetime | None = Query(default=None, description="End time"),
    feedback: str | None = Query(default=None, description="like LikedislikeUnlikecopiedCopy:"),
    sensitive_status: int | None = Query(default=None, description="Sensitive word review status"),
):
    """Export data for a list of session details"""
    result = await AuditLogService.get_session_messages(
        login_user, flow_ids, user_ids, group_ids, start_date, end_date, feedback, sensitive_status
    )
    return resp_200(data={"data": result})

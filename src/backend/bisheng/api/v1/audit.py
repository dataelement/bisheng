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
    responsible_user_ids: list[int] | None = Query(default=[], description="Filelib sync responsible person user ids"),
    start_time: datetime | None = Query(default=None, description="Start when"),
    end_time: datetime | None = Query(default=None, description="End time"),
    system_id: str | None = Query(default=None, description="Module Item"),
    event_type: str | None = Query(default=None, description="Operation behaviors"),
    page: int | None = Query(default=0, description="Page"),
    limit: int | None = Query(default=0, description="Listings Per Page"),
    user_department: str | None = Query(default=None, description="User department name"),
    user_company: str | None = Query(default=None, description="User company name"),
    user_office: str | None = Query(default=None, description="User office name"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    group_ids = [one for one in group_ids if one]
    operator_ids = [one for one in operator_ids if one]
    responsible_user_ids = [one for one in responsible_user_ids if one]
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
        responsible_user_ids=responsible_user_ids or None,
        user_department=user_department,
        user_company=user_company,
        user_office=user_office,
    )


@router.get("/responsible-persons")
async def get_all_responsible_persons(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await AuditLogService.get_all_responsible_persons(login_user))


@router.get("/user-org-options")
async def get_user_org_options(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Company, department and office names for the audit filters."""
    return resp_200(data=await AuditLogService.list_user_org_options(login_user))


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
    answer_abnormal: int | None = Query(
        default=None, ge=0, le=1, description="任务是否异常, 0否 1是. 工具准备失败且执行中未使用不算"
    ),
    user_department: str | None = Query(default=None, description="User department name"),
    user_company: str | None = Query(default=None, description="User company name"),
    user_office: str | None = Query(default=None, description="User office name"),
    page: int | None = Query(default=1, description="Page"),
    page_size: int | None = Query(default=10, description="Listings Per Page"),
):
    """Filter all session lists"""
    data, total = await AuditLogService.get_session_list(
        login_user,
        flow_ids,
        user_ids,
        group_ids,
        start_date,
        end_date,
        feedback,
        sensitive_status,
        page,
        page_size,
        answer_abnormal,
        user_department,
        user_company,
        user_office,
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
    answer_abnormal: int | None = Query(
        default=None, ge=0, le=1, description="任务是否异常, 0否 1是. 工具准备失败且执行中未使用不算"
    ),
    user_department: str | None = Query(default=None, description="User department name"),
    user_company: str | None = Query(default=None, description="User company name"),
    user_office: str | None = Query(default=None, description="User office name"),
):
    """Export data for a list of session details"""
    result = await AuditLogService.get_session_messages(
        login_user,
        flow_ids,
        user_ids,
        group_ids,
        start_date,
        end_date,
        feedback,
        sensitive_status,
        answer_abnormal,
        user_department,
        user_company,
        user_office,
    )
    return resp_200(data={"data": result})

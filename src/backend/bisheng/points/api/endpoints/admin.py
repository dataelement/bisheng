"""积分运营后台接口；所有入口都要求平台管理员。"""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.points.api.dependencies import (
    get_points_query_service,
    get_points_rule_service,
    resolve_tenant_id,
)
from bisheng.points.domain.schemas.points_schema import (
    PointAdjustRequest,
    PointCopiesUpdateRequest,
    PointDeductRequest,
    PointRuleRequest,
)
from bisheng.points.domain.services.points_query_service import PointsQueryService
from bisheng.points.domain.services.points_rule_service import PointsRuleService

router = APIRouter()


@router.get("/admin/overview")
async def overview(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """返回积分运营的三项绝对数。"""
    try:
        data = await service.overview(resolve_tenant_id(login_user), login_user)
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/admin/rules")
async def list_rules(
    rule_type: str | None = Query(None),
    status: str | None = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """列出当前租户的规则。"""
    try:
        rows = await service.list_rules(resolve_tenant_id(login_user), login_user, rule_type=rule_type, status=status)
        return resp_200([r.model_dump() for r in rows])
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/admin/rules")
async def create_rule(
    body: PointRuleRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """创建规则；不提供 DELETE，停用走 PUT status=disabled。"""
    try:
        row = await service.create_rule(resolve_tenant_id(login_user), login_user, body)
        return resp_200(row.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.put("/admin/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: PointRuleRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """编辑或启停规则。"""
    try:
        row = await service.update_rule(resolve_tenant_id(login_user), login_user, rule_id, body)
        return resp_200(row.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/admin/copies")
async def list_copies(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """管理端说明文案列表。"""
    try:
        rows = await service.list_copies(resolve_tenant_id(login_user), login_user)
        return resp_200([r.model_dump() for r in rows])
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.put("/admin/copies")
async def save_copies(
    body: PointCopiesUpdateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """批量更新前台说明文案。"""
    try:
        rows = await service.update_copies(resolve_tenant_id(login_user), login_user, body)
        return resp_200([r.model_dump() for r in rows])
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/admin/adjust")
async def adjust(
    body: PointAdjustRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """平台超管手动调分。"""
    try:
        log = await service.admin_adjust(resolve_tenant_id(login_user), login_user, body)
        return resp_200(log.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/admin/deduct")
async def deduct(
    body: PointDeductRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """平台超管按 R 规则扣减。"""
    try:
        log = await service.admin_deduct(resolve_tenant_id(login_user), login_user, body)
        return resp_200(log.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/admin/users")
async def list_users(
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """用户积分列表（姓名/部门/余额/本月净变动）。"""
    try:
        data = await service.admin_list_users(
            resolve_tenant_id(login_user),
            login_user,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/admin/users/{user_id}/detail")
async def get_user_detail(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    from_date: str | None = Query(None, description="流水起始日 YYYY-MM-DD，含当日"),
    to_date: str | None = Query(None, description="流水结束日 YYYY-MM-DD，含当日"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """用户积分详情：概况卡片 + 指定时间范围内的全量流水。"""
    from datetime import datetime, timedelta

    def _day_start(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d")

    def _day_end_exclusive(value: str | None) -> datetime | None:
        start = _day_start(value)
        return start + timedelta(days=1) if start else None

    try:
        data = await service.admin_user_detail(
            resolve_tenant_id(login_user),
            login_user,
            user_id,
            page=page,
            page_size=page_size,
            from_time=_day_start(from_date),
            to_time=_day_end_exclusive(to_date),
        )
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
    except ValueError:
        from bisheng.common.errcode.points import PointsInvalidAdjustError

        return PointsInvalidAdjustError.return_resp(msg="日期格式须为 YYYY-MM-DD")


@router.get("/admin/audit-logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int | None = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """操作记录：手动调分与 R* 扣减流水。"""
    try:
        data = await service.admin_list_audit_logs(
            resolve_tenant_id(login_user),
            login_user,
            page=page,
            page_size=page_size,
            user_id=user_id,
        )
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()

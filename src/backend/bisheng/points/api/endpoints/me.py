"""积分用户端只读接口。"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.points.api.dependencies import (
    get_optional_login_user,
    get_points_query_service,
    get_points_rule_service,
    resolve_tenant_id,
)
from bisheng.points.domain.services.points_query_service import PointsQueryService
from bisheng.points.domain.services.points_rule_service import PointsRuleService

router = APIRouter()


def _parse_day_start(value: str | None) -> datetime | None:
    """将 YYYY-MM-DD 解析为当日 00:00:00（naive）。"""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def _parse_day_end_exclusive(value: str | None) -> datetime | None:
    """将 YYYY-MM-DD 解析为次日 00:00:00，用作开区间上界。"""
    start = _parse_day_start(value)
    return start + timedelta(days=1) if start else None


@router.get("/me/summary")
async def get_summary(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """返回当前用户积分摘要；无账户时余额与当月收支为零。"""
    try:
        data = await service.my_summary(resolve_tenant_id(login_user), int(login_user.user_id))
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/me/logs")
async def get_logs(
    direction: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    from_date: str | None = Query(None, description="起始日 YYYY-MM-DD，含当日"),
    to_date: str | None = Query(None, description="结束日 YYYY-MM-DD，含当日"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """分页返回当前用户积分流水。"""
    try:
        from_time = _parse_day_start(from_date)
        to_time = _parse_day_end_exclusive(to_date)
        items, total = await service.my_logs(
            resolve_tenant_id(login_user),
            int(login_user.user_id),
            direction=direction,
            page=page,
            page_size=page_size,
            from_time=from_time,
            to_time=to_time,
        )
        return resp_200({"data": [i.model_dump() for i in items], "total": total})
    except ValueError:
        from bisheng.common.errcode.points import PointsInvalidAdjustError

        return PointsInvalidAdjustError(msg="日期格式须为 YYYY-MM-DD").return_resp_instance()
    except BaseErrorCode as exc:
        return exc.return_resp_instance()

@router.get("/rules/public")
async def get_public_rules(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    service: PointsRuleService = Depends(get_points_rule_service),
):
    """返回前台可展示规则和说明文案，不暴露月奖规则。"""
    try:
        return resp_200(await service.public_rules(resolve_tenant_id(login_user)))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/leaderboard")
async def get_leaderboard(
    period: str = Query("month", pattern="^(month|year|all)$"),
    login_user: UserPayload | None = Depends(get_optional_login_user),
    service: PointsQueryService = Depends(get_points_query_service),
):
    """读取小时快照排行榜。

    未登录与平台系统管理员默认看组织架构第一个公司；普通登录用户看所属公司。
    """
    try:
        data = await service.leaderboard(resolve_tenant_id(login_user), period, login_user)
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()

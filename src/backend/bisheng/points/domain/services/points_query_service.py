"""积分查询与管理端写操作（调分/扣减）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.points import PointsInvalidAdjustError, PointsRuleNotFoundError
from bisheng.points.domain.schemas.points_schema import (
    PointAdjustRequest,
    PointDeductRequest,
    PointLeaderboardItem,
    PointLeaderboardResponse,
    PointLogResponse,
    PointOverviewResponse,
    PointSummaryResponse,
)
from bisheng.points.domain.services.points_auth import require_platform_admin
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import PointsNotifyService

SHANGHAI = ZoneInfo("Asia/Shanghai")


class PointsQueryService:
    """聚合摘要、明细、榜单与运营概览；管理端调分/扣减封装账本与通知。"""

    def __init__(self, session, repository, ledger: PointsLedgerService, notify: PointsNotifyService | None = None):
        self.session = session
        self.repository = repository
        self.ledger = ledger
        self.notify = notify or PointsNotifyService()

    @staticmethod
    def _month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
        """返回上海时区当月起止（naive，对齐 occurred_at 落库方式）。"""
        current = now or datetime.now(SHANGHAI)
        if current.tzinfo is not None:
            current = current.astimezone(SHANGHAI)
        start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        if current.month == 12:
            end = current.replace(
                year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )
        else:
            end = current.replace(
                month=current.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )
        return start, end

    @staticmethod
    def _log_response(log) -> PointLogResponse:
        """将流水 ORM 转为响应 DTO。"""
        return PointLogResponse(
            id=int(log.id),
            title=log.title,
            delta=log.delta,
            balance_after=log.balance_after,
            direction=log.direction,
            rule_code=log.rule_code,
            source=log.source,
            remark=log.remark,
            occurred_at=log.occurred_at,
        )

    async def my_summary(self, tenant_id: int, user_id: int) -> PointSummaryResponse:
        """余额、当月收支与可选全站排名。"""
        account = await self.repository.find_account(tenant_id, user_id)
        balance = int(account.balance) if account else 0
        month_start, month_end = self._month_bounds()
        month_earned = await self.repository.sum_user_delta(
            tenant_id, user_id, direction="earn", start=month_start, end=month_end
        )
        month_deducted = abs(
            await self.repository.sum_user_delta(
                tenant_id, user_id, direction="deduct", start=month_start, end=month_end
            )
        )
        period_key = datetime.now(SHANGHAI).strftime("%Y-%m")
        global_snap = await self.repository.find_user_rank(
            tenant_id, "month", "global", None, period_key, user_id
        )
        global_rank = int(global_snap.rank_no) if global_snap else None
        if global_rank is None:
            display = "-"
        elif global_rank > 999:
            display = "999+"
        else:
            display = str(global_rank)
        # 部门榜：快照上的 dept_id 即 org_level=dept 桶；无桶则展示为 —（AC-22）。
        dept_rank = None
        if global_snap is not None and global_snap.dept_id is not None:
            dept_snap = await self.repository.find_user_rank(
                tenant_id, "month", "dept", int(global_snap.dept_id), period_key, user_id
            )
            if dept_snap is not None:
                dept_rank = int(dept_snap.rank_no)
        refreshed = await self.repository.latest_rank_refreshed_at(tenant_id, "month", period_key)
        return PointSummaryResponse(
            balance=balance,
            month_earned=month_earned,
            month_deducted=month_deducted,
            dept_rank=dept_rank,
            global_rank=global_rank,
            global_rank_display=display,
            rank_refreshed_at=refreshed,
        )

    async def my_logs(
        self,
        tenant_id: int,
        user_id: int,
        *,
        direction: str | None = None,
        page: int = 1,
        page_size: int = 20,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> tuple[list[PointLogResponse], int]:
        """分页返回当前用户流水。"""
        dir_filter = None if direction in (None, "all") else direction
        rows, total = await self.repository.list_logs(
            tenant_id,
            user_id,
            dir_filter,
            page,
            page_size,
            from_time=from_time,
            to_time=to_time,
        )
        return [self._log_response(r) for r in rows], total

    async def leaderboard(self, tenant_id: int, period: str) -> PointLeaderboardResponse:
        """读取小时快照 TOP10；未刷新时返回空列表。"""
        now = datetime.now(SHANGHAI)
        if period == "year":
            period_key = now.strftime("%Y")
        elif period == "all":
            period_key = "all"
        else:
            period = "month"
            period_key = now.strftime("%Y-%m")
        rows = await self.repository.list_top_ranks(
            tenant_id, period, "global", None, period_key, limit=10
        )
        refreshed = await self.repository.latest_rank_refreshed_at(tenant_id, period, period_key)
        items = [
            PointLeaderboardItem(
                rank=int(r.rank_no),
                user_id=int(r.user_id),
                balance=int(r.balance),
                period_score=int(r.period_score),
            )
            for r in rows
        ]
        return PointLeaderboardResponse(period=period, refreshed_at=refreshed, items=items)

    async def overview(self, tenant_id: int, user: UserPayload) -> PointOverviewResponse:
        """运营概览：总发放 / 余额合计 / 违规扣减。"""
        require_platform_admin(user)
        return PointOverviewResponse(
            total_issued=await self.repository.sum_total_issued(tenant_id),
            total_balance=await self.repository.sum_total_balance(tenant_id),
            total_violation_deducted=await self.repository.sum_violation_deducted(tenant_id),
        )

    async def admin_adjust(
        self, tenant_id: int, user: UserPayload, body: PointAdjustRequest
    ) -> PointLogResponse:
        """平台超管手动调分；提交后再发站内信。"""
        require_platform_admin(user)
        result = await self.ledger.adjust(
            tenant_id=tenant_id,
            user_id=body.user_id,
            delta=body.delta,
            title="管理员调分",
            idempotency_key=f"manual:{user.user_id}:{body.user_id}:{uuid.uuid4().hex}",
            operator_id=int(user.user_id),
            remark=body.remark,
        )
        await self.session.commit()
        if result.log_id is None:
            raise PointsInvalidAdjustError()
        log = await self.repository.get_log_by_id(int(result.log_id))
        assert log is not None
        await self.notify.notify(
            user_id=body.user_id,
            template_code="adjust_admin",
            delta=int(log.delta),
            reason=body.remark or "",
        )
        return self._log_response(log)

    async def admin_deduct(
        self, tenant_id: int, user: UserPayload, body: PointDeductRequest
    ) -> PointLogResponse:
        """平台超管按 R* 规则扣减。"""
        require_platform_admin(user)
        rule = await self.repository.get_rule(tenant_id, body.rule_code.strip().upper())
        if rule is None or rule.rule_type != "deduct" or rule.status != "enabled":
            raise PointsRuleNotFoundError()
        score = abs(int((rule.score_expr or {}).get("score", 0)))
        if score == 0:
            raise PointsInvalidAdjustError(msg="扣减规则分值为 0")
        result = await self.ledger.deduct(
            tenant_id=tenant_id,
            user_id=body.user_id,
            delta=-score,
            rule_code=rule.rule_code,
            title=rule.name,
            idempotency_key=(
                f"deduct:{rule.rule_code}:{user.user_id}:{body.user_id}:{uuid.uuid4().hex}"
            ),
            operator_id=int(user.user_id),
            remark=body.remark,
            biz_type=body.biz_type,
            biz_id=body.biz_id,
        )
        await self.session.commit()
        if result.log_id is None:
            raise PointsInvalidAdjustError()
        log = await self.repository.get_log_by_id(int(result.log_id))
        assert log is not None
        await self.notify.notify(
            user_id=body.user_id,
            template_code="deduct_admin",
            delta=abs(int(log.delta)),
            rule_name=rule.name,
            reason=body.remark or "",
        )
        return self._log_response(log)

"""积分查询与管理端写操作（调分/扣减）。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.points import PointsInvalidAdjustError, PointsRuleNotFoundError
from bisheng.common.schemas.api import PageData
from bisheng.points.domain.constants.notify_templates import format_deduct_notify_reason
from bisheng.points.domain.schemas.points_schema import (
    PointAdjustRequest,
    PointAdminDepartmentOption,
    PointAdminUserDetail,
    PointAdminUserFilterOptions,
    PointAdminUserItem,
    PointAuditLogItem,
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

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
# 运营概览缓存：三个指标均为全历史聚合，AC-19 允许 5min 陈旧。
OVERVIEW_CACHE_PREFIX = "points:overview:v2:"
OVERVIEW_CACHE_TTL = 300


def _intersect_user_ids(current: list[int] | None, new_ids: list[int]) -> list[int]:
    """合并多路 user_id 过滤条件（交集）；new_ids 为空则整表无命中。"""
    if not new_ids:
        return []
    normalized = sorted({int(uid) for uid in new_ids})
    if current is None:
        return normalized
    return sorted(set(current) & set(normalized))


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

    @staticmethod
    async def _resolve_user_company_id(user_id: int) -> int | None:
        """解析用户主部门所属公司根 id；无公司标签返回 None。"""
        from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
        from bisheng.points.domain.services.points_rank_service import resolve_company_id

        primary_map = UserDepartmentDao.get_primary_department_map_by_user_ids([int(user_id)])
        primary = primary_map.get(int(user_id))
        all_depts = await DepartmentDao.aget_all_active()
        dept_by_id = {int(d.id): d for d in all_depts}
        return resolve_company_id(primary, dept_by_id)

    @staticmethod
    async def _resolve_first_company_id() -> int | None:
        """组织架构第一个公司根 id；当前租户无公司标签时返回 None。"""
        from bisheng.database.models.department import DepartmentDao
        from bisheng.points.domain.services.points_rank_service import resolve_first_company_id

        all_depts = await DepartmentDao.aget_all_active()
        dept_by_id = {int(d.id): d for d in all_depts}
        return resolve_first_company_id(dept_by_id)

    async def _resolve_leaderboard_company_id(self, user) -> int | None:
        """首页榜公司：访客/平台超管取组织树第一家；普通人取所属公司。"""
        from bisheng.points.domain.services.points_auth import is_platform_super_admin

        if user is None or is_platform_super_admin(user):
            return await self._resolve_first_company_id()
        return await self._resolve_user_company_id(int(user.user_id))

    async def my_summary(self, tenant_id: int, user_id: int) -> PointSummaryResponse:
        """余额、当月收支与本公司排名（无公司则排名为 —）。"""
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
        company_id = await self._resolve_user_company_id(user_id)
        global_snap = None
        if company_id is not None:
            global_snap = await self.repository.find_user_rank(
                tenant_id, "month", "global", company_id, period_key, user_id
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

    async def leaderboard(self, tenant_id: int, period: str, user=None) -> PointLeaderboardResponse:
        """读取首页积分榜小时快照前十（算法甲含并列）。

        普通人看所属公司；未登录与平台系统管理员看组织架构第一个公司。
        解析不到公司则空榜（AC-15）。
        """
        now = datetime.now(SHANGHAI)
        if period == "year":
            period_key = now.strftime("%Y")
        elif period == "all":
            period_key = "all"
        else:
            period = "month"
            period_key = now.strftime("%Y-%m")
        from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id, set_current_tenant_id

        # 访客无 JWT 时中间件可能未注入租户；公开榜按默认租户读部门/快照。
        if get_current_tenant_id() is None:
            set_current_tenant_id(int(tenant_id or DEFAULT_TENANT_ID))
        company_id = await self._resolve_leaderboard_company_id(user)
        refreshed = await self.repository.latest_rank_refreshed_at(tenant_id, period, period_key)
        if company_id is None:
            return PointLeaderboardResponse(period=period, refreshed_at=refreshed, items=[])
        from bisheng.points.domain.services.points_rank_service import select_top_n_with_score_ties

        # 先取整桶排序结果，再按第 10 名分值阈值纳入全部并列（人数可 >10）。
        bucket_rows = await self.repository.list_top_ranks(
            tenant_id, period, "global", company_id, period_key, limit=10
        )
        rows = select_top_n_with_score_ties(bucket_rows, top_n=10)
        user_ids = [int(r.user_id) for r in rows]
        name_by_user, dept_by_user = await self._leaderboard_display_maps(user_ids)
        items = [
            PointLeaderboardItem(
                rank=int(r.rank_no),
                user_id=int(r.user_id),
                user_name=name_by_user.get(int(r.user_id), str(r.user_id)),
                dept_name=dept_by_user.get(int(r.user_id), "—"),
                balance=int(r.balance),
                period_score=int(r.period_score),
            )
            for r in rows
        ]
        return PointLeaderboardResponse(period=period, refreshed_at=refreshed, items=items)

    @staticmethod
    def _department_path_ids(path: str | None) -> list[int]:
        """从 materialized path 抽出部门 id，例如 ``/1/54/55/94/`` → ``[1, 54, 55, 94]``。"""
        ids: list[int] = []
        for part in str(path or "").strip("/").split("/"):
            if part.isdigit():
                ids.append(int(part))
        return ids

    @staticmethod
    async def _leaderboard_display_maps(
        user_ids: list[int],
    ) -> tuple[dict[int, str], dict[int, str]]:
        """批量解析用户名与积分部门名称。

        部门名取主部门沿 path 向上最近的 ``org_level=dept`` 节点，与部门榜桶一致；
        展示名优先 ``short_name``。找不到该标签时不回退叶子/主部门，调用方按 ``—`` 展示（AC-22）。
        """
        if not user_ids:
            return {}, {}
        from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
        from bisheng.department.domain.services.department_display_service import get_department_display_name
        from bisheng.points.domain.services.points_rank_service import resolve_dept_bucket_id
        from bisheng.user.domain.models.user import UserDao

        users = await UserDao.aget_user_by_ids(user_ids) or []
        name_by_user = {int(u.user_id): str(getattr(u, "user_name", None) or u.user_id) for u in users}
        primary_map = UserDepartmentDao.get_primary_department_map_by_user_ids(user_ids)
        dept_by_id: dict[int, object] = {}
        ancestor_ids: set[int] = set()
        for dept in primary_map.values():
            dept_id = getattr(dept, "id", None)
            if dept_id is not None:
                dept_by_id[int(dept_id)] = dept
            ancestor_ids.update(PointsQueryService._department_path_ids(getattr(dept, "path", None)))
        missing_ids = [dept_id for dept_id in ancestor_ids if dept_id not in dept_by_id]
        if missing_ids:
            for row in await DepartmentDao.aget_by_ids(missing_ids):
                if getattr(row, "id", None) is not None:
                    dept_by_id[int(row.id)] = row
        dept_by_user: dict[int, str] = {}
        for uid, primary in primary_map.items():
            bucket_id = resolve_dept_bucket_id(primary, dept_by_id)
            node = dept_by_id.get(bucket_id) if bucket_id is not None else None
            if node is None:
                continue
            display = get_department_display_name(
                str(getattr(node, "name", "") or ""),
                getattr(node, "short_name", None),
            ).strip()
            if display:
                dept_by_user[int(uid)] = display
        return name_by_user, dept_by_user

    async def overview(self, tenant_id: int, user: UserPayload) -> PointOverviewResponse:
        """运营概览：总发放 / 有效可用总积分 / 违规扣减。

        当前有效可用总积分 = 平台总积分发放 − 违规扣减积分（非账户余额合计）。
        三个指标都是全历史聚合，耗时随流水量线性增长；按 AC-19 允许 5min 陈旧，
        因此走 Redis 缓存。缓存不可用时退化为直查库，不影响可用性。
        """
        require_platform_admin(user)
        cache_key = f"{OVERVIEW_CACHE_PREFIX}{tenant_id}"
        cached = await self._overview_cache_get(cache_key)
        if cached is not None:
            return PointOverviewResponse(**cached)
        month_start, month_end = self._month_bounds()
        total_issued = await self.repository.sum_total_issued(tenant_id)
        total_violation_deducted = await self.repository.sum_violation_deducted(tenant_id)
        payload = {
            "total_issued": total_issued,
            "total_balance": max(0, total_issued - total_violation_deducted),
            "total_violation_deducted": total_violation_deducted,
            "total_issued_mom": await self.repository.sum_tenant_earn(tenant_id, month_start, month_end),
        }
        await self._overview_cache_set(cache_key, payload)
        return PointOverviewResponse(**payload)

    @staticmethod
    async def _overview_cache_get(key: str) -> dict | None:
        """读概览缓存；Redis 不可用时按未命中处理。"""
        try:
            from bisheng.core.cache.redis_manager import get_redis_client

            cached = await (await get_redis_client()).aget(key)
        except Exception:
            # 概览是只读统计，缓存故障时直接查库即可，无需中断请求。
            logger.warning("points.overview cache read failed key=%s", key, exc_info=True)
            return None
        return cached if isinstance(cached, dict) else None

    @staticmethod
    async def _overview_cache_set(key: str, payload: dict) -> None:
        """写概览缓存；失败仅告警，不影响本次返回。"""
        try:
            from bisheng.core.cache.redis_manager import get_redis_client

            await (await get_redis_client()).aset(key, payload, expiration=OVERVIEW_CACHE_TTL)
        except Exception:
            logger.warning("points.overview cache write failed key=%s", key, exc_info=True)

    async def admin_user_filter_options(self, user: UserPayload) -> PointAdminUserFilterOptions:
        """用户积分列表筛选项：公司→部门两级 + PRD 四类角色。

        仅返回 org_level 为 company / dept 的活跃节点；科室/班组与未打标不进入下拉。
        """
        require_platform_admin(user)
        from bisheng.database.models.department import DepartmentDao
        from bisheng.department.domain.services.department_display_service import get_department_display_name
        from bisheng.points.domain.constants.admin_user_type import USER_TYPE_FILTER_OPTIONS
        from bisheng.points.domain.constants.org_levels import ORG_LEVEL_COMPANY

        rows = await DepartmentDao.aget_all_active()
        companies: list[PointAdminDepartmentOption] = []
        depts: list[PointAdminDepartmentOption] = []
        company_ids: set[int] = set()
        for row in rows:
            level = getattr(row, "org_level", None)
            if level not in (ORG_LEVEL_COMPANY, "dept"):
                continue
            name = get_department_display_name(row.name, getattr(row, "short_name", None))
            item = PointAdminDepartmentOption(
                id=int(row.id),
                name=name,
                org_level=str(level),
                parent_id=None
                if level == ORG_LEVEL_COMPANY
                else (int(row.parent_id) if row.parent_id is not None else None),
            )
            if level == ORG_LEVEL_COMPANY:
                companies.append(item)
                company_ids.add(int(row.id))
            else:
                depts.append(item)

        # 部门必须挂在已知公司下；孤儿 dept（parent 不是公司）剔除，避免破坏两级展示。
        depts = [d for d in depts if d.parent_id is not None and d.parent_id in company_ids]
        companies.sort(key=lambda item: item.name)
        depts.sort(key=lambda item: (item.parent_id or 0, item.name))
        # 扁平输出：公司在前，其后各部门（FE 按 parent_id 分组）；保持稳定顺序便于测试。
        ordered: list[PointAdminDepartmentOption] = []
        for company in companies:
            ordered.append(company)
            ordered.extend(d for d in depts if d.parent_id == company.id)
        return PointAdminUserFilterOptions(
            departments=ordered,
            user_types=list(USER_TYPE_FILTER_OPTIONS),
        )

    async def admin_list_users(
        self,
        tenant_id: int,
        user: UserPayload,
        *,
        keyword: str | None = None,
        dept_id: int | None = None,
        user_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PageData[PointAdminUserItem]:
        """管理端用户积分列表（账户 + 姓名/积分部门桶 + 本月净变动）。"""
        require_platform_admin(user)
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 100)
        user_ids_filter: list[int] | None = None
        kw = (keyword or "").strip()
        if kw:
            from bisheng.user.domain.models.user import UserDao

            matched = await UserDao.aget_users_by_username(kw)
            # 精确同名可能只有少量；再做 like 搜索兜底
            like_rows = UserDao.search_user_by_name(kw) or []
            ids = {int(u.user_id) for u in (matched or [])} | {int(u.user_id) for u in like_rows}
            # 纯数字关键词按 user_id 命中
            if kw.isdigit():
                ids.add(int(kw))
            user_ids_filter = _intersect_user_ids(user_ids_filter, sorted(ids))
        if dept_id is not None:
            from bisheng.database.models.department import UserDepartmentDao

            dept_user_ids = await UserDepartmentDao.aget_user_ids_by_department(int(dept_id), is_primary=True)
            user_ids_filter = _intersect_user_ids(user_ids_filter, dept_user_ids)
        role_label = (user_type or "").strip()
        if role_label:
            from bisheng.points.domain.constants.admin_user_type import resolve_user_ids_for_user_type_filter

            account_user_ids = await self.repository.list_account_user_ids(tenant_id)
            role_user_ids = await resolve_user_ids_for_user_type_filter(
                role_label,
                account_user_ids=account_user_ids,
            )
            if role_user_ids is not None:
                user_ids_filter = _intersect_user_ids(user_ids_filter, role_user_ids)
        accounts, total = await self.repository.list_accounts_page(
            tenant_id, page=page, page_size=page_size, user_ids=user_ids_filter
        )
        ids = [int(a.user_id) for a in accounts]
        name_by_user, dept_by_user = await self._leaderboard_display_maps(ids)
        start, end = self._month_bounds()
        # 只聚合当页用户；此前是对全租户整月流水做 GROUP BY 后再取子集。
        month_scores = await self.repository.sum_deltas_by_users(tenant_id, ids, start=start, end=end)
        from bisheng.points.domain.constants.admin_user_type import (
            resolve_user_types_for_admin_list,
        )

        user_type_by_user = await resolve_user_types_for_admin_list(ids)
        data = [
            PointAdminUserItem(
                user_id=int(a.user_id),
                user_name=name_by_user.get(int(a.user_id), str(a.user_id)),
                dept_name=dept_by_user.get(int(a.user_id), "—"),
                user_type=user_type_by_user.get(int(a.user_id), "普通用户"),
                balance=int(a.balance),
                month_score=int(month_scores.get(int(a.user_id), 0)),
            )
            for a in accounts
        ]
        return PageData(data=data, total=total)

    async def admin_user_detail(
        self,
        tenant_id: int,
        user: UserPayload,
        target_user_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> PointAdminUserDetail:
        """管理端用户积分详情：身份概况 + 本月收支卡片 + 时间范围内全量流水。"""
        require_platform_admin(user)
        uid = int(target_user_id)
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 100)

        account = await self.repository.find_account(tenant_id, uid)
        name_by_user, dept_by_user = await self._leaderboard_display_maps([uid])
        month_start, month_end = self._month_bounds()
        month_earned = await self.repository.sum_user_delta(
            tenant_id, uid, direction="earn", start=month_start, end=month_end
        )
        month_deducted = abs(
            await self.repository.sum_user_delta(tenant_id, uid, direction="deduct", start=month_start, end=month_end)
        )
        from bisheng.points.domain.constants.admin_user_type import resolve_user_types_for_admin_list

        # 与列表「角色」列同源：积分用户类型（空间管理角色），不用 RBAC 角色名。
        user_type_by_user = await resolve_user_types_for_admin_list([uid])
        role_label = user_type_by_user.get(uid, "普通用户")

        logs, logs_total = await self.my_logs(
            tenant_id,
            uid,
            page=page,
            page_size=page_size,
            from_time=from_time,
            to_time=to_time,
        )
        return PointAdminUserDetail(
            user_id=uid,
            user_name=name_by_user.get(uid, str(uid)),
            dept_name=dept_by_user.get(uid, "—"),
            role_label=role_label,
            balance=int(account.balance) if account else 0,
            month_earned=int(month_earned or 0),
            month_deducted=int(month_deducted or 0),
            logs=logs,
            logs_total=int(logs_total),
        )

    @staticmethod
    async def _resolve_user_role_label(user_id: int) -> str:
        """解析用户角色展示名；无角色时默认「普通用户」。

        管理端详情已改用 ``resolve_user_types_for_admin_list``；本方法保留给其他调用方。
        """
        try:
            from bisheng.database.models.role import RoleDao
            from bisheng.user.domain.models.user_role import UserRoleDao

            links = await UserRoleDao.aget_user_roles(int(user_id))
            role_ids = [int(r.role_id) for r in (links or []) if getattr(r, "role_id", None) is not None]
            if not role_ids:
                return "普通用户"
            roles = await RoleDao.aget_role_by_ids(role_ids)
            names = [str(r.role_name).strip() for r in (roles or []) if getattr(r, "role_name", None)]
            names = [n for n in names if n]
            return "、".join(names) if names else "普通用户"
        except Exception:
            logger.exception("points.admin_user_detail resolve role failed user_id=%s", user_id)
            return "普通用户"

    async def admin_list_audit_logs(
        self,
        tenant_id: int,
        user: UserPayload,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: int | None = None,
    ) -> PageData[PointAuditLogItem]:
        """管理端操作记录：手动调分 / R* 扣减。"""
        require_platform_admin(user)
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 100)
        rows, total = await self.repository.list_audit_logs(
            tenant_id,
            page=page,
            page_size=page_size,
            sources=["manual_adjust", "manual_deduct"],
            user_id=user_id,
        )
        subject_ids = sorted({int(r.user_id) for r in rows})
        operator_ids = sorted({int(r.operator_id) for r in rows if r.operator_id is not None})
        name_by_user, _ = await self._leaderboard_display_maps(sorted(set(subject_ids) | set(operator_ids)))
        data = [
            PointAuditLogItem(
                id=int(r.id),
                user_id=int(r.user_id),
                user_name=name_by_user.get(int(r.user_id), str(r.user_id)),
                title=r.title,
                delta=int(r.delta),
                balance_after=int(r.balance_after),
                direction=r.direction,
                rule_code=r.rule_code,
                source=r.source,
                operator_id=r.operator_id,
                operator_name=(
                    name_by_user.get(int(r.operator_id), str(r.operator_id)) if r.operator_id is not None else "—"
                ),
                remark=r.remark,
                occurred_at=r.occurred_at,
            )
            for r in rows
        ]
        return PageData(data=data, total=total)

    async def admin_adjust(self, tenant_id: int, user: UserPayload, body: PointAdjustRequest) -> PointLogResponse:
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
        delta = int(log.delta)
        if delta >= 0:
            await self.notify.notify(
                user_id=body.user_id,
                template_code="adjust_admin_add",
                delta=delta,
                reason=(body.remark or "").strip() or "—",
            )
        else:
            await self.notify.notify(
                user_id=body.user_id,
                template_code="adjust_admin_deduct",
                delta=abs(delta),
                reason=(body.remark or "").strip() or "—",
            )
        return self._log_response(log)

    async def admin_deduct(self, tenant_id: int, user: UserPayload, body: PointDeductRequest) -> PointLogResponse:
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
            idempotency_key=(f"deduct:{rule.rule_code}:{user.user_id}:{body.user_id}:{uuid.uuid4().hex}"),
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
            reason=format_deduct_notify_reason(rule_name=rule.name, remark=body.remark),
        )
        return self._log_response(log)

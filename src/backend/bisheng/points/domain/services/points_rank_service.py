"""积分排行快照：按公司隔离的月/年/总榜与部门桶；稠密并列名次。"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import Department, DepartmentDao, UserDepartmentDao
from bisheng.points.domain.constants.org_levels import ORG_LEVEL_COMPANY, ORG_LEVEL_DEPT
from bisheng.points.domain.models import PointRankSnapshot
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.user.domain.models.user_role import UserRole

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def period_keys(now: datetime | None = None) -> dict[str, str]:
    """返回当前上海时区的 period → period_key。"""
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is not None:
        current = current.astimezone(SHANGHAI)
    return {
        "month": current.strftime("%Y-%m"),
        "year": current.strftime("%Y"),
        "all": "all",
    }


def year_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """上海时区自然年起止（naive）。"""
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is not None:
        current = current.astimezone(SHANGHAI)
    start = current.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end = current.replace(year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return start, end


def _department_path_ids(path: str | None) -> list[int]:
    """从 materialized path 抽出部门 id，例如 ``/1/54/`` → ``[1, 54]``。"""
    parts: list[int] = []
    for part in str(path or "").strip("/").split("/"):
        if part.isdigit():
            parts.append(int(part))
    return parts


def resolve_company_id(
    primary: Department | None,
    departments: dict[int, Department],
) -> int | None:
    """主部门沿 path 向上找最近 org_level=company；找不到返回 None。"""
    if primary is None or not primary.path:
        return None
    for dept_id in reversed(_department_path_ids(primary.path)):
        node = departments.get(dept_id)
        if node is not None and getattr(node, "org_level", None) == ORG_LEVEL_COMPANY:
            return int(node.id)
    return None


def resolve_first_company_id(departments: dict[int, Department]) -> int | None:
    """组织架构树前序中第一个 ``org_level=company`` 节点。

    同级顺序与部门树一致：``sort_order`` 升序，再按 id。无公司标签时返回 None。
    用途：未登录访客与平台系统管理员看首页积分榜的默认公司。
    """
    companies = [
        node
        for node in departments.values()
        if getattr(node, "org_level", None) == ORG_LEVEL_COMPANY and getattr(node, "id", None) is not None
    ]
    if not companies:
        return None

    def _tree_key(node) -> tuple:
        key: list[tuple[int, int]] = []
        for dept_id in _department_path_ids(getattr(node, "path", None)):
            ancestor = departments.get(dept_id)
            sort_order = int(getattr(ancestor, "sort_order", 0) or 0) if ancestor is not None else 0
            key.append((sort_order, dept_id))
        if not key:
            key.append((int(getattr(node, "sort_order", 0) or 0), int(node.id)))
        return tuple(key)

    companies.sort(key=_tree_key)
    return int(companies[0].id)


def resolve_dept_bucket_id(
    primary: Department | None,
    departments: dict[int, Department],
) -> int | None:
    """主部门沿 path 向上找最近 org_level=dept；找不到返回 None（AC-22）。"""
    if primary is None or not primary.path:
        return None
    parts: list[int] = []
    for part in str(primary.path).strip("/").split("/"):
        if part.isdigit():
            parts.append(int(part))
    for dept_id in reversed(parts):
        node = departments.get(dept_id)
        if node is not None and getattr(node, "org_level", None) == ORG_LEVEL_DEPT:
            return int(node.id)
    return None


def build_ranked_rows(
    *,
    tenant_id: int,
    period: str,
    scope: str,
    scope_id: int | None,
    period_key: str,
    scores: dict[int, int],
    balances: dict[int, int],
    dept_ids: dict[int, int | None],
    exclude_user_ids: set[int],
    refreshed_at: datetime,
    last_earned_at: dict[int, datetime | None] | None = None,
) -> list[PointRankSnapshot]:
    """按分降序生成快照；同分看 last_earned_at 升序再 user_id；名次仍按分稠密并列。"""
    earned_map = last_earned_at or {}
    candidates = [
        (user_id, score, earned_map.get(user_id))
        for user_id, score in scores.items()
        if user_id not in exclude_user_ids
    ]
    # 无获得时间的排在同分末尾，再比 user_id。
    candidates.sort(
        key=lambda item: (
            -int(item[1]),
            item[2] is None,
            item[2] or datetime.min,
            int(item[0]),
        )
    )
    rows: list[PointRankSnapshot] = []
    prev_score: int | None = None
    rank_no = 0
    for user_id, score, earned_at in candidates:
        score_i = int(score)
        # 稠密名次：分不同才 +1；同分共用上一名次（100,100,90 → 1,1,2）。
        if prev_score is None or score_i != prev_score:
            rank_no += 1
            prev_score = score_i
        rows.append(
            PointRankSnapshot(
                tenant_id=tenant_id,
                period=period,
                scope=scope,
                scope_id=scope_id,
                period_key=period_key,
                user_id=user_id,
                rank_no=rank_no,
                period_score=score_i,
                balance=int(balances.get(user_id, 0)),
                dept_id=dept_ids.get(user_id),
                last_earned_at=earned_at,
                refreshed_at=refreshed_at,
            )
        )
    return rows


def select_top_n_with_score_ties(rows: list, *, top_n: int = 10) -> list:
    """算法甲：按已排序列表取第 N 人的分作阈值，纳入所有 ≥ 该分的行。

    ``rows`` 须已按 period_score 降序（同分 last_earned_at / user_id 已排好）。
    """
    if top_n <= 0 or not rows:
        return []
    if len(rows) <= top_n:
        return list(rows)
    threshold = int(rows[top_n - 1].period_score)
    return [row for row in rows if int(row.period_score) >= threshold]


class PointsRankService:
    """重建并写入 point_rank_snapshot。"""

    def __init__(self, repository: PointsRepository | None = None):
        self.repository = repository

    async def refresh_rank_snapshots(self, tenant_id: int) -> dict:
        """刷新指定租户的 month/year/all × 公司 global / dept 快照。"""
        async with get_async_db_session() as session:
            repo = self.repository or PointsRepository(session)
            result = await self._refresh_with_repo(repo, int(tenant_id))
            await session.commit()
            return result

    async def refresh_all_tenants(self) -> dict:
        """Beat 入口：扫有账户的租户并刷新。"""
        from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                tenant_ids = await repo.list_tenant_ids_with_accounts()
        totals = {"tenants": 0, "rows": 0}
        for tid in tenant_ids or [1]:
            set_current_tenant_id(int(tid))
            try:
                out = await self.refresh_rank_snapshots(int(tid))
                totals["tenants"] += 1
                totals["rows"] += int(out.get("rows") or 0)
            except Exception:
                logger.exception("points.rank.refresh_failed tenant_id=%s", tid)
        return totals

    async def _refresh_with_repo(self, repo: PointsRepository, tenant_id: int) -> dict:
        now = datetime.now(SHANGHAI)
        keys = period_keys(now)
        refreshed_at = now.replace(tzinfo=None)
        accounts = await repo.list_accounts(tenant_id)
        balances = {int(a.user_id): int(a.balance) for a in accounts}
        lifetime_earned = {int(a.user_id): int(a.lifetime_earned) for a in accounts}
        last_earned_at = {int(a.user_id): getattr(a, "last_earned_at", None) for a in accounts}
        if not balances:
            return {"tenant_id": tenant_id, "rows": 0}

        from bisheng.points.domain.services.points_query_service import PointsQueryService

        month_start, month_end = PointsQueryService._month_bounds(now)
        year_start, year_end = year_bounds(now)
        month_scores = await repo.sum_deltas_by_user(tenant_id, start=month_start, end=month_end)
        year_scores = await repo.sum_deltas_by_user(tenant_id, start=year_start, end=year_end)
        all_scores = {user_id: earned for user_id, earned in lifetime_earned.items() if earned > 0}

        exclude = await self._load_super_admin_ids()
        company_by_user, bucket_by_user = await self._load_company_and_dept_buckets(list(balances.keys()))
        company_ids = sorted({cid for cid in company_by_user.values() if cid is not None})

        written = 0
        period_score_map = {
            "month": month_scores,
            "year": year_scores,
            "all": all_scores,
        }
        for period, scores in period_score_map.items():
            period_key = keys[period]
            # 整 period 清桶，去掉旧全租户 global(scope_id=NULL) 与失效公司桶。
            await repo.clear_period_rank_snapshots(tenant_id, period, period_key)
            period_rows: list[PointRankSnapshot] = []

            for company_id in company_ids:
                company_scores = {
                    uid: sc
                    for uid, sc in scores.items()
                    if company_by_user.get(uid) == company_id and uid not in exclude
                }
                period_rows.extend(
                    build_ranked_rows(
                        tenant_id=tenant_id,
                        period=period,
                        scope="global",
                        scope_id=company_id,
                        period_key=period_key,
                        scores=company_scores,
                        balances=balances,
                        dept_ids=bucket_by_user,
                        exclude_user_ids=set(),
                        refreshed_at=refreshed_at,
                        last_earned_at=last_earned_at,
                    )
                )

                buckets: dict[int, dict[int, int]] = {}
                for user_id, score in company_scores.items():
                    bucket = bucket_by_user.get(user_id)
                    if bucket is None:
                        continue
                    buckets.setdefault(bucket, {})[user_id] = score
                for scope_id, bucket_scores in buckets.items():
                    period_rows.extend(
                        build_ranked_rows(
                            tenant_id=tenant_id,
                            period=period,
                            scope="dept",
                            scope_id=scope_id,
                            period_key=period_key,
                            scores=bucket_scores,
                            balances=balances,
                            dept_ids=bucket_by_user,
                            exclude_user_ids=set(),
                            refreshed_at=refreshed_at,
                            last_earned_at=last_earned_at,
                        )
                    )

            written += await repo.bulk_insert_rank_snapshots(period_rows)

        logger.info(
            "points.rank.refreshed tenant_id=%s rows=%s companies=%s periods=%s",
            tenant_id,
            written,
            len(company_ids),
            list(keys.values()),
        )
        return {
            "tenant_id": tenant_id,
            "rows": written,
            "period_keys": keys,
            "companies": len(company_ids),
        }

    @staticmethod
    async def _load_super_admin_ids() -> set[int]:
        """平台超管（AdminRole）不进激励榜。"""
        from sqlmodel import select

        async with get_async_db_session() as session:
            rows = (await session.exec(select(UserRole.user_id).where(UserRole.role_id == AdminRole))).all()
        return {int(r[0] if isinstance(r, tuple) else r) for r in rows}

    @staticmethod
    async def _load_company_and_dept_buckets(
        user_ids: list[int],
    ) -> tuple[dict[int, int | None], dict[int, int | None]]:
        """批量解析用户主部门 → 公司根与 dept 桶。"""
        if not user_ids:
            return {}, {}
        primary_map = UserDepartmentDao.get_primary_department_map_by_user_ids(user_ids)
        all_depts = await DepartmentDao.aget_all_active()
        dept_by_id = {int(d.id): d for d in all_depts}
        companies: dict[int, int | None] = {}
        buckets: dict[int, int | None] = {}
        for user_id in user_ids:
            primary = primary_map.get(int(user_id))
            companies[int(user_id)] = resolve_company_id(primary, dept_by_id)
            buckets[int(user_id)] = resolve_dept_bucket_id(primary, dept_by_id)
        return companies, buckets

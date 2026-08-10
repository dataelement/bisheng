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
    end = current.replace(
        year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return start, end


def resolve_company_id(
    primary: Department | None,
    departments: dict[int, Department],
) -> int | None:
    """主部门沿 path 向上找最近 org_level=company；找不到返回 None。"""
    if primary is None or not primary.path:
        return None
    parts: list[int] = []
    for part in str(primary.path).strip("/").split("/"):
        if part.isdigit():
            parts.append(int(part))
    for dept_id in reversed(parts):
        node = departments.get(dept_id)
        if node is not None and getattr(node, "org_level", None) == ORG_LEVEL_COMPANY:
            return int(node.id)
    return None


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
) -> list[PointRankSnapshot]:
    """按 period_score 降序生成快照行；同分稠密同名次，列表序按 user_id 稳定。"""
    candidates = [
        (user_id, score)
        for user_id, score in scores.items()
        if user_id not in exclude_user_ids
    ]
    candidates.sort(key=lambda item: (-item[1], item[0]))
    rows: list[PointRankSnapshot] = []
    prev_score: int | None = None
    rank_no = 0
    for user_id, score in candidates:
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
                refreshed_at=refreshed_at,
            )
        )
    return rows


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
        if not balances:
            return {"tenant_id": tenant_id, "rows": 0}

        from bisheng.points.domain.services.points_query_service import PointsQueryService

        month_start, month_end = PointsQueryService._month_bounds(now)
        year_start, year_end = year_bounds(now)
        month_scores = await repo.sum_deltas_by_user(tenant_id, start=month_start, end=month_end)
        year_scores = await repo.sum_deltas_by_user(tenant_id, start=year_start, end=year_end)
        all_scores = {
            user_id: earned for user_id, earned in lifetime_earned.items() if earned > 0
        }

        exclude = await self._load_super_admin_ids()
        company_by_user, bucket_by_user = await self._load_company_and_dept_buckets(
            list(balances.keys())
        )
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
            rows = (
                await session.exec(select(UserRole.user_id).where(UserRole.role_id == AdminRole))
            ).all()
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

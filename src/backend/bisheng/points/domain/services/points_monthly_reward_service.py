"""管理员月奖：次月 1 日结算上月，登录≥1，多角色取最高 M*。"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import select

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao
from bisheng.points.domain.constants.monthly_reward_rules import (
    MONTHLY_RULE_MATCHERS,
    MonthlyRuleMatcher,
    fixed_score,
    pick_highest_reward,
)
from bisheng.points.domain.constants.notify_templates import resolve_earn_notify
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import (
    PointsNotifyService,
    build_points_notify_service,
)
from bisheng.user.domain.models.user_role import UserRole

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")

LoginUsersFn = Callable[[int, str, str], Awaitable[set[int]]]


def previous_month_key(now: datetime | None = None) -> str:
    """返回应结算的上月 period key（Asia/Shanghai）。"""
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is not None:
        current = current.astimezone(SHANGHAI)
    else:
        current = current.replace(tzinfo=SHANGHAI)
    first = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


def month_local_date_bounds(period_key: str) -> tuple[str, str]:
    """`YYYY-MM` → 当月首末日 `YYYY-MM-DD`（含）。"""
    year_s, month_s = period_key.split("-", 1)
    year, month = int(year_s), int(month_s)
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


async def default_login_users(tenant_id: int, start_date: str, end_date: str) -> set[int]:
    """从日活事实索引取上月至少登录过一次的用户。"""
    from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection
    from bisheng.telemetry.domain.mid_table.daily_participation import DailyParticipationFact

    client = await get_statistics_es_connection()
    # BaseMidTable 是 Pydantic BaseModel：类属性 _index_name 是 PrivateAttr，
    # 类访问会得到 ModelPrivateAttr，ES 会去查字面量 default='…'。必须取实例值。
    index = DailyParticipationFact(ensure_sync_index=False)._index_name
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"tenant_id": str(tenant_id)}},
                    {"range": {"local_date": {"gte": start_date, "lte": end_date}}},
                    {
                        "bool": {
                            "should": [
                                {"term": {"logged_in": True}},
                                {"range": {"login_count": {"gt": 0}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ]
            }
        },
        "aggs": {
            "users": {
                "terms": {
                    "field": "user_id",
                    "size": 10000,
                }
            }
        },
    }
    try:
        resp = await client.search(index=index, body=body)
    except Exception:
        logger.exception(
            "points.monthly.login_query_failed tenant_id=%s %s..%s",
            tenant_id,
            start_date,
            end_date,
        )
        raise
    buckets = (((resp or {}).get("aggregations") or {}).get("users") or {}).get("buckets") or []
    result: set[int] = set()
    for bucket in buckets:
        key = bucket.get("key")
        try:
            result.add(int(key))
        except (TypeError, ValueError):
            continue
    return result


class PointsMonthlyRewardService:
    """扫描空间角色并发放上月管理员月奖。"""

    def __init__(
        self,
        *,
        login_users_fn: LoginUsersFn | None = None,
        notify: PointsNotifyService | None = None,
    ):
        self._login_users_fn = login_users_fn or default_login_users
        self.notify = notify or PointsNotifyService()

    async def run_all_tenants(self, now: datetime | None = None) -> dict:
        """Beat 入口：按有账户或默认租户发放。"""
        from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id

        period_key = previous_month_key(now)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                tenant_ids = await repo.list_tenant_ids_with_accounts()
        totals = {"period_key": period_key, "tenants": 0, "awarded": 0, "skipped": 0}
        for tid in tenant_ids or [1]:
            set_current_tenant_id(int(tid))
            try:
                out = await self.run_for_tenant(int(tid), period_key=period_key)
                totals["tenants"] += 1
                totals["awarded"] += int(out.get("awarded") or 0)
                totals["skipped"] += int(out.get("skipped") or 0)
            except Exception:
                logger.exception("points.monthly.tenant_failed tenant_id=%s", tid)
        return totals

    async def run_for_tenant(self, tenant_id: int, *, period_key: str | None = None) -> dict:
        """对单个租户结算指定月（默认上月）。"""
        month_key = period_key or previous_month_key()
        start_date, end_date = month_local_date_bounds(month_key)
        async with get_async_db_session() as session:
            repo = PointsRepository(session)
            rules = await repo.list_rules(tenant_id, rule_type="admin_reward", status="enabled")
        rule_by_code = {r.rule_code: r for r in rules}
        active_matchers = {
            code: matcher
            for code, matcher in MONTHLY_RULE_MATCHERS.items()
            if code in rule_by_code and fixed_score(rule_by_code[code].score_expr) > 0
        }
        if not active_matchers:
            return {"tenant_id": tenant_id, "period_key": month_key, "awarded": 0, "skipped": 0}

        user_candidates = await self._collect_user_candidates(active_matchers, rule_by_code)
        if not user_candidates:
            return {"tenant_id": tenant_id, "period_key": month_key, "awarded": 0, "skipped": 0}

        exclude = await self._load_super_admin_ids()
        try:
            logged_in = await self._login_users_fn(tenant_id, start_date, end_date)
        except Exception:
            # 日活不可用时整租户跳过，避免误发无登录校验的奖励。
            return {
                "tenant_id": tenant_id,
                "period_key": month_key,
                "awarded": 0,
                "skipped": len(user_candidates),
                "error": "login_query_failed",
            }

        awarded = 0
        skipped = 0
        for user_id, (rule_code, score) in user_candidates.items():
            if user_id in exclude:
                skipped += 1
                continue
            if user_id not in logged_in:
                skipped += 1
                continue
            rule = rule_by_code[rule_code]
            ok = await self._award_one(
                tenant_id=tenant_id,
                user_id=user_id,
                rule_code=rule_code,
                rule_name=rule.name or rule_code,
                score=score,
                period_key=month_key,
            )
            if ok:
                awarded += 1
            else:
                skipped += 1

        logger.info(
            "points.monthly.done tenant_id=%s period=%s awarded=%s skipped=%s",
            tenant_id,
            month_key,
            awarded,
            skipped,
        )
        return {
            "tenant_id": tenant_id,
            "period_key": month_key,
            "awarded": awarded,
            "skipped": skipped,
        }

    async def _award_one(
        self,
        *,
        tenant_id: int,
        user_id: int,
        rule_code: str,
        rule_name: str,
        score: int,
        period_key: str,
    ) -> bool:
        """单用户单月幂等入账；失败只记日志。"""
        key = f"reward:{rule_code}:{user_id}:{period_key}"
        try:
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                # 入账会话不挂 MessageService，避免消息依赖阻断月奖。
                ledger = PointsLedgerService(repo)
                result = await ledger.award(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    delta=score,
                    title=rule_name,
                    rule_code=rule_code,
                    idempotency_key=key,
                    source="monthly_reward",
                    biz_type="monthly_reward",
                    biz_id=period_key,
                    beneficiary_role="subject",
                )
                await session.commit()
            if result.replayed or result.skipped_cap:
                return bool(result.replayed)
            await self._notify_earn(
                user_id=user_id,
                rule_code=rule_code,
                rule_name=rule_name,
                delta=score,
            )
            return True
        except Exception:
            logger.exception(
                "points.monthly.award_failed user_id=%s rule=%s key=%s",
                user_id,
                rule_code,
                key,
            )
            return False

    async def _notify_earn(
        self,
        *,
        user_id: int,
        rule_code: str,
        rule_name: str,
        delta: int,
    ) -> None:
        """账本提交后发送月奖站内信；注入 MessageService，失败不影响入账。"""
        template, values = resolve_earn_notify(rule_code, rule_name=rule_name, delta=delta)
        try:
            # 已注入可用 message_service，或单测 mock：直接发；裸 PointsNotifyService() 则走工厂。
            if self.notify is not None and (
                not isinstance(self.notify, PointsNotifyService) or self.notify.message_service is not None
            ):
                await self.notify.notify(
                    user_id=user_id,
                    template_code=template,
                    **values,
                )
                return
            async with get_async_db_session() as session:
                notify = await build_points_notify_service(session)
                await notify.notify(
                    user_id=user_id,
                    template_code=template,
                    **values,
                )
                await session.commit()
        except Exception:
            logger.exception("points.monthly.notify_failed user_id=%s", user_id)

    async def _collect_user_candidates(
        self,
        matchers: dict[str, MonthlyRuleMatcher],
        rule_by_code: dict,
    ) -> dict[int, tuple[str, int]]:
        """聚合用户 → 最高分 M*。"""
        # level → [(rule_code, roles)]
        by_level: dict[str, list[tuple[str, set[str]]]] = {}
        for code, matcher in matchers.items():
            for level in matcher.levels:
                by_level.setdefault(level, []).append((code, set(matcher.roles)))

        # user_id → [(rule_code, score)]
        raw: dict[int, list[tuple[str, int]]] = {}
        for level, entries in by_level.items():
            space_ids = await KnowledgeSpaceScopeDao.aget_space_ids_by_levels([level])
            if not space_ids:
                continue
            needed_roles: set[str] = set()
            for _, roles in entries:
                needed_roles |= roles
            role_enums = [UserRoleEnum(role) for role in needed_roles]
            members = await self._list_managers_for_spaces(space_ids, role_enums)
            for member in members:
                role_value = getattr(member.user_role, "value", member.user_role)
                user_id = int(member.user_id)
                for rule_code, roles in entries:
                    if role_value not in roles:
                        continue
                    score = fixed_score(rule_by_code[rule_code].score_expr)
                    raw.setdefault(user_id, []).append((rule_code, score))

        result: dict[int, tuple[str, int]] = {}
        for user_id, candidates in raw.items():
            best = pick_highest_reward(candidates)
            if best is not None:
                result[user_id] = best
        return result

    @staticmethod
    async def _list_managers_for_spaces(
        space_ids: list[int],
        roles: list[UserRoleEnum],
    ) -> list[SpaceChannelMember]:
        """批量读取空间 creator/admin 成员。"""
        if not space_ids or not roles:
            return []
        business_ids = [str(sid) for sid in space_ids]
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(SpaceChannelMember).where(
                        SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                        SpaceChannelMember.business_id.in_(business_ids),
                        SpaceChannelMember.status == MembershipStatusEnum.ACTIVE,
                        SpaceChannelMember.user_role.in_(roles),
                    )
                )
            ).all()
        return list(rows)

    @staticmethod
    async def _load_super_admin_ids() -> set[int]:
        """平台超管不获月奖（Q16）。"""
        async with get_async_db_session() as session:
            rows = (await session.exec(select(UserRole.user_id).where(UserRole.role_id == AdminRole))).all()
        return {int(r[0] if isinstance(r, tuple) else r) for r in rows}

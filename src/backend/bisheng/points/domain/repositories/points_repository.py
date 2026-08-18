"""积分仓储：集中持有 ORM 读写，服务层不直接拼装查询。"""

from datetime import datetime

from sqlalchemy import and_, delete, func, insert, or_
from sqlmodel import select

from bisheng.points.domain.models import (
    PointCopy,
    PointFavoriteTierAward,
    PointPendingDeduct,
    PointRankSnapshot,
    PointRule,
    PointSyncOutbox,
    UserPointAccount,
    UserPointLog,
)

# 排行快照批量插入的分片大小，避免单条语句超过 max_allowed_packet。
RANK_SNAPSHOT_INSERT_CHUNK = 2000


class PointsRepository:
    """在调用方事务中执行积分账户、流水、规则与快照读写。"""

    def __init__(self, session):
        self.session = session

    async def lock_or_create_account(self, tenant_id: int, user_id: int) -> UserPointAccount:
        """锁定用户账户；并发首建通过嵌套事务吸收唯一键竞争。"""
        row = (
            await self.session.exec(
                select(UserPointAccount)
                .where(UserPointAccount.tenant_id == tenant_id, UserPointAccount.user_id == user_id)
                .with_for_update()
            )
        ).first()
        if row:
            return row
        try:
            async with self.session.begin_nested():
                row = UserPointAccount(tenant_id=tenant_id, user_id=user_id)
                self.session.add(row)
                await self.session.flush()
        except Exception:
            # 并发首建撞唯一键时回读并重新加锁。
            row = (
                await self.session.exec(
                    select(UserPointAccount)
                    .where(UserPointAccount.tenant_id == tenant_id, UserPointAccount.user_id == user_id)
                    .with_for_update()
                )
            ).one()
        return row

    async def find_account(self, tenant_id: int, user_id: int) -> UserPointAccount | None:
        """按租户与用户读取账户；无账户时返回 None。"""
        return (
            await self.session.exec(
                select(UserPointAccount).where(
                    UserPointAccount.tenant_id == tenant_id,
                    UserPointAccount.user_id == user_id,
                )
            )
        ).first()

    async def get_log_by_idempotency(self, tenant_id: int, key: str) -> UserPointLog | None:
        """按幂等键获取已写入流水。"""
        return (
            await self.session.exec(
                select(UserPointLog).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.idempotency_key == key,
                )
            )
        ).first()

    async def get_log_by_id(self, log_id: int) -> UserPointLog | None:
        """按主键读取流水。"""
        return (await self.session.exec(select(UserPointLog).where(UserPointLog.id == log_id))).first()

    async def sum_earn_today(self, tenant_id: int, user_id: int, rule_code: str, start: datetime) -> int:
        """汇总上海业务日内同规则已获得分数。

        必须在账户行锁之后调用。``FOR UPDATE`` 走当前读，避免 REPEATABLE READ
        下 Facade 先读规则定下的快照看不见排队事务刚提交的流水。
        """
        rows = (
            await self.session.exec(
                select(UserPointLog.delta)
                .where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.user_id == user_id,
                    UserPointLog.rule_code == rule_code,
                    UserPointLog.direction == "earn",
                    UserPointLog.occurred_at >= start,
                )
                .with_for_update()
            )
        ).all()
        total = 0
        for row in rows:
            total += int(row[0] if isinstance(row, tuple) else row or 0)
        return total

    async def sum_user_delta(
        self,
        tenant_id: int,
        user_id: int,
        *,
        direction: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """汇总用户在时间窗内某方向的 delta 合计。"""
        value = (
            await self.session.exec(
                select(func.coalesce(func.sum(UserPointLog.delta), 0)).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.user_id == user_id,
                    UserPointLog.direction == direction,
                    UserPointLog.occurred_at >= start,
                    UserPointLog.occurred_at < end,
                )
            )
        ).one()
        return int(value[0] if isinstance(value, tuple) else value or 0)

    async def append_log(self, log: UserPointLog) -> UserPointLog:
        """追加账本流水并刷新主键。"""
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_outbox(self, tenant_id: int, log_id: int, payload: dict) -> None:
        """为已写流水建立待同步记录。"""
        self.session.add(PointSyncOutbox(tenant_id=tenant_id, log_id=log_id, payload=payload))

    async def list_logs(
        self,
        tenant_id: int,
        user_id: int,
        direction: str | None,
        page: int,
        page_size: int,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ):
        """分页查询用户流水，按发生时间倒序。"""
        filters = [
            UserPointLog.tenant_id == tenant_id,
            UserPointLog.user_id == user_id,
        ]
        if direction:
            filters.append(UserPointLog.direction == direction)
        if from_time is not None:
            filters.append(UserPointLog.occurred_at >= from_time)
        if to_time is not None:
            filters.append(UserPointLog.occurred_at < to_time)
        total = (await self.session.exec(select(func.count()).select_from(UserPointLog).where(*filters))).one()
        rows = (
            await self.session.exec(
                select(UserPointLog)
                .where(*filters)
                .order_by(UserPointLog.occurred_at.desc(), UserPointLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total[0] if isinstance(total, tuple) else total)

    async def get_rule(self, tenant_id: int, rule_code: str) -> PointRule | None:
        """按编码读取规则。"""
        return (
            await self.session.exec(
                select(PointRule).where(PointRule.tenant_id == tenant_id, PointRule.rule_code == rule_code)
            )
        ).first()

    async def get_rule_by_id(self, rule_id: int) -> PointRule | None:
        """按主键读取规则。"""
        return (await self.session.exec(select(PointRule).where(PointRule.id == rule_id))).first()

    async def list_rules(
        self,
        tenant_id: int,
        *,
        rule_type: str | None = None,
        status: str | None = None,
    ) -> list[PointRule]:
        """列出租户规则，按 sort_order、id 排序。"""
        stmt = select(PointRule).where(PointRule.tenant_id == tenant_id)
        if rule_type:
            stmt = stmt.where(PointRule.rule_type == rule_type)
        if status:
            stmt = stmt.where(PointRule.status == status)
        rows = (await self.session.exec(stmt.order_by(PointRule.sort_order, PointRule.id))).all()
        return list(rows)

    async def save_rule(self, rule: PointRule) -> PointRule:
        """持久化规则并刷新。"""
        self.session.add(rule)
        await self.session.flush()
        await self.session.refresh(rule)
        return rule

    async def list_copies(self, tenant_id: int) -> list[PointCopy]:
        """列出租户说明文案。"""
        rows = (
            await self.session.exec(
                select(PointCopy).where(PointCopy.tenant_id == tenant_id).order_by(PointCopy.sort_order, PointCopy.id)
            )
        ).all()
        return list(rows)

    async def upsert_copies(self, tenant_id: int, items: list[dict]) -> list[PointCopy]:
        """按 copy_key 批量更新文案内容；不存在则创建。

        Keys present for the tenant but missing from ``items`` are deleted
        (replace-set semantics — product keeps a single ``guide`` row).
        """
        result: list[PointCopy] = []
        keep_keys: set[str] = set()
        for item in items:
            key = item["copy_key"]
            keep_keys.add(key)
            row = (
                await self.session.exec(
                    select(PointCopy).where(PointCopy.tenant_id == tenant_id, PointCopy.copy_key == key)
                )
            ).first()
            if row is None:
                row = PointCopy(
                    tenant_id=tenant_id,
                    copy_key=key,
                    content=item["content"],
                    sort_order=int(item.get("sort_order") or 0),
                )
            else:
                row.content = item["content"]
                if "sort_order" in item and item["sort_order"] is not None:
                    row.sort_order = int(item["sort_order"])
            self.session.add(row)
            result.append(row)

        existing = (await self.session.exec(select(PointCopy).where(PointCopy.tenant_id == tenant_id))).all()
        for row in existing:
            if row.copy_key not in keep_keys:
                await self.session.delete(row)

        await self.session.flush()
        return result

    async def sum_total_issued(self, tenant_id: int) -> int:
        """租户累计发放（earn 方向 delta 之和）。"""
        value = (
            await self.session.exec(
                select(func.coalesce(func.sum(UserPointLog.delta), 0)).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.direction == "earn",
                )
            )
        ).one()
        return int(value[0] if isinstance(value, tuple) else value or 0)

    async def sum_tenant_earn(self, tenant_id: int, start: datetime, end: datetime) -> int:
        """汇总租户在时间窗内的 earn 发放合计。"""
        value = (
            await self.session.exec(
                select(func.coalesce(func.sum(UserPointLog.delta), 0)).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.direction == "earn",
                    UserPointLog.occurred_at >= start,
                    UserPointLog.occurred_at < end,
                )
            )
        ).one()
        return int(value[0] if isinstance(value, tuple) else value or 0)

    async def sum_total_balance(self, tenant_id: int) -> int:
        """租户当前余额合计。"""
        value = (
            await self.session.exec(
                select(func.coalesce(func.sum(UserPointAccount.balance), 0)).where(
                    UserPointAccount.tenant_id == tenant_id
                )
            )
        ).one()
        return int(value[0] if isinstance(value, tuple) else value or 0)

    async def sum_violation_deducted(self, tenant_id: int) -> int:
        """违规扣减合计：manual_deduct + 负向 manual_adjust 的绝对值。"""
        value = (
            await self.session.exec(
                select(func.coalesce(func.sum(UserPointLog.delta), 0)).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.direction == "deduct",
                    or_(
                        UserPointLog.source == "manual_deduct",
                        and_(UserPointLog.source == "manual_adjust", UserPointLog.delta < 0),
                    ),
                )
            )
        ).one()
        raw = int(value[0] if isinstance(value, tuple) else value or 0)
        return abs(raw)

    async def find_user_rank(
        self,
        tenant_id: int,
        period: str,
        scope: str,
        scope_id: int | None,
        period_key: str,
        user_id: int,
    ) -> PointRankSnapshot | None:
        """读取用户在指定榜单桶中的排名快照。"""
        stmt = select(PointRankSnapshot).where(
            PointRankSnapshot.tenant_id == tenant_id,
            PointRankSnapshot.period == period,
            PointRankSnapshot.scope == scope,
            PointRankSnapshot.period_key == period_key,
            PointRankSnapshot.user_id == user_id,
        )
        if scope_id is None:
            stmt = stmt.where(PointRankSnapshot.scope_id.is_(None))
        else:
            stmt = stmt.where(PointRankSnapshot.scope_id == scope_id)
        return (await self.session.exec(stmt)).first()

    async def list_top_ranks(
        self,
        tenant_id: int,
        period: str,
        scope: str,
        scope_id: int | None,
        period_key: str,
        *,
        limit: int = 10,
    ) -> list[PointRankSnapshot]:
        """读取公司/部门桶快照，按首页榜排序键返回。

        排序：分降序 → 最近获得时间升序（空在后）→ user_id。
        ``limit`` 保留兼容；截断（算法甲）由查询服务按名次深度处理。
        """
        stmt = select(PointRankSnapshot).where(
            PointRankSnapshot.tenant_id == tenant_id,
            PointRankSnapshot.period == period,
            PointRankSnapshot.scope == scope,
            PointRankSnapshot.period_key == period_key,
        )
        if scope_id is None:
            stmt = stmt.where(PointRankSnapshot.scope_id.is_(None))
        else:
            stmt = stmt.where(PointRankSnapshot.scope_id == scope_id)
        # MySQL/DM8：用 IS NULL 分组把空获得时间排到同分末尾，避免 nulls_last 方言差异。
        rows = (
            await self.session.exec(
                stmt.order_by(
                    PointRankSnapshot.period_score.desc(),
                    PointRankSnapshot.last_earned_at.is_(None),
                    PointRankSnapshot.last_earned_at.asc(),
                    PointRankSnapshot.user_id.asc(),
                )
            )
        ).all()
        _ = limit
        return list(rows)

    async def latest_rank_refreshed_at(self, tenant_id: int, period: str, period_key: str) -> datetime | None:
        """返回指定榜单最近刷新时间。"""
        value = (
            await self.session.exec(
                select(func.max(PointRankSnapshot.refreshed_at)).where(
                    PointRankSnapshot.tenant_id == tenant_id,
                    PointRankSnapshot.period == period,
                    PointRankSnapshot.period_key == period_key,
                )
            )
        ).one()
        if value is None:
            return None
        return value[0] if isinstance(value, tuple) else value

    async def get_favorite_tier_award(
        self,
        tenant_id: int,
        file_id: int,
        *,
        for_update: bool = False,
    ) -> PointFavoriteTierAward | None:
        """读取文档已发放的 G3 最高档记录。

        :param for_update: 发分路径在账户行锁之后应加行锁，读取最新已提交进度。
        """
        stmt = select(PointFavoriteTierAward).where(
            PointFavoriteTierAward.tenant_id == tenant_id,
            PointFavoriteTierAward.file_id == file_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.exec(stmt)).first()

    async def upsert_favorite_tier_award(
        self,
        tenant_id: int,
        file_id: int,
        *,
        highest_tier: int,
        points_granted_total: int,
    ) -> PointFavoriteTierAward:
        """更新或创建 G3 档位发放进度，取消收藏后也不回退。"""
        row = await self.get_favorite_tier_award(tenant_id, file_id)
        if row is None:
            row = PointFavoriteTierAward(
                tenant_id=tenant_id,
                file_id=file_id,
                highest_tier=highest_tier,
                points_granted_total=points_granted_total,
            )
        else:
            # 仅抬升已授分数/档位，避免收藏人数回落后被重复补发。
            row.highest_tier = max(int(row.highest_tier), highest_tier)
            row.points_granted_total = max(int(row.points_granted_total), points_granted_total)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_accounts(self, tenant_id: int) -> list[UserPointAccount]:
        """列出租户全部积分账户。"""
        rows = (await self.session.exec(select(UserPointAccount).where(UserPointAccount.tenant_id == tenant_id))).all()
        return list(rows)

    async def list_accounts_page(
        self,
        tenant_id: int,
        *,
        page: int,
        page_size: int,
        user_ids: list[int] | None = None,
    ) -> tuple[list[UserPointAccount], int]:
        """分页列出积分账户；可按 user_ids 过滤（关键词预解析后传入）。"""
        filters = [UserPointAccount.tenant_id == tenant_id]
        if user_ids is not None:
            if not user_ids:
                return [], 0
            filters.append(UserPointAccount.user_id.in_(user_ids))
        total = (await self.session.exec(select(func.count()).select_from(UserPointAccount).where(*filters))).one()
        rows = (
            await self.session.exec(
                select(UserPointAccount)
                .where(*filters)
                .order_by(UserPointAccount.balance.desc(), UserPointAccount.user_id.asc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total[0] if isinstance(total, tuple) else total)

    async def list_account_user_ids(self, tenant_id: int) -> list[int]:
        """租户下全部积分账户 user_id（角色筛「普通用户」用）。"""
        rows = (
            await self.session.exec(select(UserPointAccount.user_id).where(UserPointAccount.tenant_id == tenant_id))
        ).all()
        return sorted({int(r[0] if isinstance(r, tuple) else r) for r in rows})

    async def list_audit_logs(
        self,
        tenant_id: int,
        *,
        page: int,
        page_size: int,
        sources: list[str] | None = None,
        user_id: int | None = None,
    ) -> tuple[list[UserPointLog], int]:
        """管理端审计：默认看 manual/deduct；可扩 source。"""
        filters = [UserPointLog.tenant_id == tenant_id]
        if sources:
            filters.append(UserPointLog.source.in_(sources))
        if user_id is not None:
            filters.append(UserPointLog.user_id == int(user_id))
        total = (await self.session.exec(select(func.count()).select_from(UserPointLog).where(*filters))).one()
        rows = (
            await self.session.exec(
                select(UserPointLog)
                .where(*filters)
                .order_by(UserPointLog.occurred_at.desc(), UserPointLog.id.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total[0] if isinstance(total, tuple) else total)

    async def list_tenant_ids_with_accounts(self) -> list[int]:
        """返回存在积分账户的租户 id（Beat 扫租户用）。"""
        rows = (await self.session.exec(select(UserPointAccount.tenant_id).distinct())).all()
        return sorted({int(r[0] if isinstance(r, tuple) else r) for r in rows})

    async def sum_deltas_by_user(
        self,
        tenant_id: int,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[int, int]:
        """按用户汇总时间窗内全部 delta（月/年净变动）。"""
        rows = (
            await self.session.exec(
                select(UserPointLog.user_id, func.coalesce(func.sum(UserPointLog.delta), 0))
                .where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.occurred_at >= start,
                    UserPointLog.occurred_at < end,
                )
                .group_by(UserPointLog.user_id)
            )
        ).all()
        result: dict[int, int] = {}
        for row in rows:
            user_id, total = row[0], row[1]
            result[int(user_id)] = int(total or 0)
        return result

    async def sum_deltas_by_users(
        self,
        tenant_id: int,
        user_ids: list[int],
        *,
        start: datetime,
        end: datetime,
    ) -> dict[int, int]:
        """按给定用户集合汇总时间窗内 delta。

        供管理端列表按页取值：只聚合当页用户，避免为 20 行数据扫全租户整月流水。
        user_ids 为空时直接返回空字典，不发查询。
        """
        if not user_ids:
            return {}
        rows = (
            await self.session.exec(
                select(UserPointLog.user_id, func.coalesce(func.sum(UserPointLog.delta), 0))
                .where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.user_id.in_(user_ids),
                    UserPointLog.occurred_at >= start,
                    UserPointLog.occurred_at < end,
                )
                .group_by(UserPointLog.user_id)
            )
        ).all()
        return {int(row[0]): int(row[1] or 0) for row in rows}

    async def sum_lifetime_deltas_by_user(self, tenant_id: int) -> dict[int, int]:
        """按用户汇总全部流水 delta（对账期望余额）。"""
        rows = (
            await self.session.exec(
                select(UserPointLog.user_id, func.coalesce(func.sum(UserPointLog.delta), 0))
                .where(UserPointLog.tenant_id == tenant_id)
                .group_by(UserPointLog.user_id)
            )
        ).all()
        result: dict[int, int] = {}
        for row in rows:
            user_id, total = row[0], row[1]
            result[int(user_id)] = int(total or 0)
        return result

    async def list_due_sync_outbox(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[PointSyncOutbox]:
        """列出到期可投递的 pending/failed outbox（跨租户时需 bypass）。"""
        current = now or datetime.utcnow()
        rows = (
            await self.session.exec(
                select(PointSyncOutbox)
                .where(
                    PointSyncOutbox.status.in_(["pending", "failed"]),
                    or_(
                        PointSyncOutbox.next_retry_at.is_(None),
                        PointSyncOutbox.next_retry_at <= current,
                    ),
                )
                .order_by(PointSyncOutbox.id)
                .limit(limit)
            )
        ).all()
        return list(rows)

    async def save_outbox(self, row: PointSyncOutbox) -> PointSyncOutbox:
        """持久化 outbox 状态变更。"""
        self.session.add(row)
        await self.session.flush()
        return row

    async def clear_dept_rank_snapshots(self, tenant_id: int, period: str, period_key: str) -> None:
        """删除某 period_key 下全部部门桶快照（刷新前清僵尸桶）。"""
        await self.session.exec(
            delete(PointRankSnapshot).where(
                PointRankSnapshot.tenant_id == tenant_id,
                PointRankSnapshot.period == period,
                PointRankSnapshot.scope == "dept",
                PointRankSnapshot.period_key == period_key,
            )
        )

    async def clear_period_rank_snapshots(self, tenant_id: int, period: str, period_key: str) -> None:
        """删除某 period_key 下全部快照（含旧全租户 global 与各公司/部门桶）。"""
        await self.session.exec(
            delete(PointRankSnapshot).where(
                PointRankSnapshot.tenant_id == tenant_id,
                PointRankSnapshot.period == period,
                PointRankSnapshot.period_key == period_key,
            )
        )

    @staticmethod
    def _snapshot_values(rows: list[PointRankSnapshot]) -> list[dict]:
        """快照 ORM 对象 → 批量插入用的字典列表。

        故意不带 id 与 create_time：分别交给自增主键与库端默认值，
        与逐行 ORM 插入时的落库结果保持一致。
        """
        return [
            {
                "tenant_id": row.tenant_id,
                "period": row.period,
                "scope": row.scope,
                "scope_id": row.scope_id,
                "period_key": row.period_key,
                "user_id": row.user_id,
                "rank_no": row.rank_no,
                "period_score": row.period_score,
                "balance": row.balance,
                "dept_id": row.dept_id,
                "last_earned_at": row.last_earned_at,
                "refreshed_at": row.refreshed_at,
            }
            for row in rows
        ]

    async def bulk_insert_rank_snapshots(self, rows: list[PointRankSnapshot]) -> int:
        """批量写入排行快照（不含删除）；返回写入行数。

        用 Core 批量 insert 而非逐行 ``session.add()``：MySQL 无 RETURNING，ORM flush
        为回填自增主键会退化成一行一条 INSERT（实测 4.2 万行约 12s，批量后约 0.5s）。
        这些行在 ``build_ranked_rows`` 里已显式带上 tenant_id，因此绕过 before_flush
        的租户回填不影响正确性。
        """
        if not rows:
            return 0
        values = self._snapshot_values(rows)
        for start in range(0, len(values), RANK_SNAPSHOT_INSERT_CHUNK):
            await self.session.execute(insert(PointRankSnapshot), values[start : start + RANK_SNAPSHOT_INSERT_CHUNK])
        return len(rows)

    async def replace_rank_snapshots(
        self,
        tenant_id: int,
        period: str,
        scope: str,
        scope_id: int | None,
        period_key: str,
        rows: list[PointRankSnapshot],
    ) -> int:
        """删除同一榜单维度后写入新快照；返回写入行数。"""
        stmt = delete(PointRankSnapshot).where(
            PointRankSnapshot.tenant_id == tenant_id,
            PointRankSnapshot.period == period,
            PointRankSnapshot.scope == scope,
            PointRankSnapshot.period_key == period_key,
        )
        if scope_id is None:
            stmt = stmt.where(PointRankSnapshot.scope_id.is_(None))
        else:
            stmt = stmt.where(PointRankSnapshot.scope_id == scope_id)
        await self.session.exec(stmt)
        return await self.bulk_insert_rank_snapshots(rows)

    async def get_pending_deduct_by_key(self, tenant_id: int, idempotency_key: str) -> PointPendingDeduct | None:
        """按幂等键读取补扣行。"""
        return (
            await self.session.exec(
                select(PointPendingDeduct).where(
                    PointPendingDeduct.tenant_id == tenant_id,
                    PointPendingDeduct.idempotency_key == idempotency_key,
                )
            )
        ).first()

    async def upsert_pending_deduct(self, row: PointPendingDeduct) -> PointPendingDeduct:
        """插入补扣行；同幂等键已存在则返回已有行（并发安全）。"""
        existing = await self.get_pending_deduct_by_key(int(row.tenant_id), row.idempotency_key)
        if existing is not None:
            return existing
        self.session.add(row)
        try:
            await self.session.flush()
            return row
        except Exception:
            # 唯一键冲突：回滚本次 flush 后读已有行（独立 session 场景下安全）。
            await self.session.rollback()
            existing = await self.get_pending_deduct_by_key(int(row.tenant_id), row.idempotency_key)
            if existing is not None:
                return existing
            raise

    async def list_due_pending_deducts(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[PointPendingDeduct]:
        """列出到期可重试的补扣任务。"""
        current = now or datetime.utcnow()
        rows = (
            await self.session.exec(
                select(PointPendingDeduct)
                .where(
                    PointPendingDeduct.status == "pending",
                    or_(
                        PointPendingDeduct.next_retry_at.is_(None),
                        PointPendingDeduct.next_retry_at <= current,
                    ),
                )
                .order_by(PointPendingDeduct.id)
                .limit(limit)
            )
        ).all()
        return list(rows)

    async def save_pending_deduct(self, row: PointPendingDeduct) -> PointPendingDeduct:
        """持久化补扣行状态。"""
        self.session.add(row)
        await self.session.flush()
        return row

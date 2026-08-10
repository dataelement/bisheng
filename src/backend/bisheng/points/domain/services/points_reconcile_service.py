"""积分余额对账：核对 sum(log.delta) 与 account.balance，只告警不改流水。"""

from __future__ import annotations

import logging

from bisheng.core.database import get_async_db_session
from bisheng.points.domain.repositories.points_repository import PointsRepository

logger = logging.getLogger(__name__)


class PointsReconcileService:
    """日对账任务；发现不一致仅记录，禁止静默改流水（AC-04）。"""

    async def reconcile_all_tenants(self) -> dict:
        """扫有账户的租户并逐一核对。"""
        from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                tenant_ids = await repo.list_tenant_ids_with_accounts()
        totals = {"tenants": 0, "checked": 0, "mismatches": 0}
        for tid in tenant_ids or [1]:
            set_current_tenant_id(int(tid))
            try:
                out = await self.reconcile_tenant(int(tid))
                totals["tenants"] += 1
                totals["checked"] += int(out.get("checked") or 0)
                totals["mismatches"] += int(out.get("mismatches") or 0)
            except Exception:
                logger.exception("points.reconcile.tenant_failed tenant_id=%s", tid)
        if totals["mismatches"]:
            logger.error("points.reconcile.done_with_mismatches %s", totals)
        else:
            logger.info("points.reconcile.done %s", totals)
        return totals

    async def reconcile_tenant(self, tenant_id: int) -> dict:
        """核对单租户：期望余额 = 流水 delta 之和。"""
        async with get_async_db_session() as session:
            repo = PointsRepository(session)
            accounts = await repo.list_accounts(tenant_id)
            ledger_sums = await repo.sum_lifetime_deltas_by_user(tenant_id)

        mismatches: list[dict] = []
        checked = 0
        seen_users: set[int] = set()
        for account in accounts:
            user_id = int(account.user_id)
            seen_users.add(user_id)
            expected = int(ledger_sums.get(user_id, 0))
            actual = int(account.balance)
            checked += 1
            if expected != actual:
                item = {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "balance": actual,
                    "ledger_sum": expected,
                }
                mismatches.append(item)
                logger.error("points.reconcile.mismatch %s", item)

        # 有流水但无账户的异常行也告警（通常不应出现）。
        for user_id, expected in ledger_sums.items():
            if int(user_id) in seen_users:
                continue
            checked += 1
            item = {
                "tenant_id": tenant_id,
                "user_id": int(user_id),
                "balance": None,
                "ledger_sum": int(expected),
            }
            mismatches.append(item)
            logger.error("points.reconcile.orphan_ledger %s", item)

        return {
            "tenant_id": tenant_id,
            "checked": checked,
            "mismatches": len(mismatches),
            "details": mismatches[:50],
        }

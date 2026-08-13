#!/usr/bin/env python3
"""测试1-1 验收辅助：规则快照 / 月度引擎 dry-run。

用法：
  cd src/backend && PYTHONPATH=. config=config.yaml \\
    .venv/bin/python test/e2e_ui/points/helpers/accept_test11_trigger.py <action>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 全量 G/R/M（本轮验收要求全部启用）
TARGET_CODES = (
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "G6",
    "G7",
    "R1",
    "R2",
    "R3",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "M8",
)


async def _rules_snapshot(tenant_id: int = 1) -> dict:
    """拉取目标规则启用状态与分值表达式。"""
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        rules = await repo.list_rules(tenant_id)
    by_code = {r.rule_code: r for r in rules}
    items = []
    missing = []
    for code in TARGET_CODES:
        rule = by_code.get(code)
        if not rule:
            missing.append(code)
            continue
        items.append(
            {
                "rule_code": rule.rule_code,
                "status": rule.status,
                "name": rule.name,
                "rule_type": rule.rule_type,
                "score_expr": rule.score_expr,
                "beneficiary": rule.beneficiary,
            }
        )
    enabled = [i["rule_code"] for i in items if i["status"] == "enabled"]
    return {
        "ok": not missing and set(enabled) == set(TARGET_CODES),
        "items": items,
        "missing": missing,
        "enabled": enabled,
    }


async def _monthly_probe(tenant_id: int = 1, period_key: str | None = None) -> dict:
    """调用月度奖励引擎一次（会真实尝试结算；缺 ES 登录事实时返回 error）。"""
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.services.points_monthly_reward_service import (
        PointsMonthlyRewardService,
        previous_month_key,
    )

    svc = PointsMonthlyRewardService()
    key = period_key or previous_month_key()
    out = await svc.run_for_tenant(int(tenant_id), period_key=key)
    blocked = out.get("error") == "login_query_failed"
    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                text(
                    "select rule_code, count(*) c, coalesce(sum(delta),0) s "
                    "from user_point_log where tenant_id=:t and source='monthly_reward' "
                    "and biz_id=:p group by rule_code order by rule_code"
                ),
                {"t": int(tenant_id), "p": key},
            )
        ).all()
    by_rule = {str(r[0]): {"count": int(r[1]), "sum_delta": int(r[2])} for r in rows}
    return {
        "ok": True,
        "blocked": blocked,
        "result": out,
        "ledger_by_rule": by_rule,
        "period_key": key,
    }


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "rules_snapshot":
        out = await _rules_snapshot()
    elif action == "monthly_probe":
        tid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        period = sys.argv[3] if len(sys.argv) > 3 else None
        out = await _monthly_probe(tid, period)
    else:
        print(json.dumps({"error": f"unknown action {action}"}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

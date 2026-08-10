#!/usr/bin/env python3
"""G-M4 API 辅助：受益人发分校验 / 规则查询 / 恢复 G1 beneficiary。

用法：
  cd src/backend && PYTHONPATH=. .venv/bin/python test/e2e_ui/points/helpers/gm4_trigger.py <action> ...
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _get_rule_beneficiary(rule_code: str, tenant_id: int = 1) -> dict:
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        rule = await repo.get_rule(tenant_id, rule_code.upper())
        if not rule:
            return {"ok": False, "error": "rule_not_found"}
        return {
            "ok": True,
            "rule_code": rule.rule_code,
            "beneficiary": rule.beneficiary,
            "status": rule.status,
        }


async def _set_rule_beneficiary(rule_code: str, beneficiary: str, tenant_id: int = 1) -> dict:
    """测试辅助：直接改库 beneficiary（Gate 收尾恢复用）。"""
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        rule = await repo.get_rule(tenant_id, rule_code.upper())
        if not rule:
            return {"ok": False, "error": "rule_not_found"}
        prev = rule.beneficiary
        rule.beneficiary = beneficiary
        await repo.save_rule(rule)
        await session.commit()
        return {"ok": True, "rule_code": rule.rule_code, "prev": prev, "beneficiary": beneficiary}


async def _award_g1_split(uploader_id: int, publisher_id: int, file_id: int | None = None) -> dict:
    """按当前 G1 beneficiary 发分；uploader 与 publisher 不同，用于断言落点。"""
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository
    from bisheng.points.domain.services.points_award_facade import PointsAwardFacade, SpaceFileReadyEvent
    from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
    from sqlalchemy import text

    fid = int(file_id or (int(time.time()) % 1_000_000 + 910_000_000))
    space_id = 91001

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        rule = await repo.get_rule(1, "G1")
        if not rule or rule.status != "enabled":
            return {"ok": False, "error": "g1_missing_or_disabled"}
        facade = PointsAwardFacade(repo, PointsLedgerService(repo), enabled=True)
        outcome = await facade.on_space_file_ready(
            SpaceFileReadyEvent(
                tenant_id=1,
                space_id=space_id,
                space_level="public",
                file_id=fid,
                uploader_id=int(uploader_id),
                publisher_id=int(publisher_id),
                is_favorite_space=False,
                space_manager_ids=frozenset(),
            )
        )
        await session.commit()
        key = f"earn:G1:{fid}:{space_id}"
        rows = (
            await session.execute(
                text(
                    "select user_id, delta, beneficiary_role from user_point_log "
                    "where tenant_id=1 and idempotency_key=:k"
                ),
                {"k": key},
            )
        ).all()

    return {
        "ok": True,
        "file_id": fid,
        "space_id": space_id,
        "key": key,
        "beneficiary_config": rule.beneficiary,
        "skipped": outcome.skipped,
        "reason": outcome.reason,
        "logs": [
            {
                "user_id": int(r[0]),
                "delta": int(r[1]),
                "beneficiary_role": r[2],
            }
            for r in rows
        ],
    }


async def _latest_deduct(user_id: int, rule_code: str = "R1") -> dict:
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        row = (
            await session.execute(
                text(
                    "select id, delta, direction, source, balance_after, remark "
                    "from user_point_log "
                    "where tenant_id=1 and user_id=:u and rule_code=:r "
                    "and source='manual_deduct' order by id desc limit 1"
                ),
                {"u": int(user_id), "r": rule_code.upper()},
            )
        ).first()
    if not row:
        return {"ok": True, "found": False}
    return {
        "ok": True,
        "found": True,
        "id": int(row[0]),
        "delta": int(row[1]),
        "direction": row[2],
        "source": row[3],
        "balance_after": int(row[4]),
        "remark": row[5],
    }


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "get_beneficiary":
        out = await _get_rule_beneficiary(sys.argv[2])
    elif action == "set_beneficiary":
        out = await _set_rule_beneficiary(sys.argv[2], sys.argv[3])
    elif action == "award_g1_split":
        file_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
        out = await _award_g1_split(int(sys.argv[2]), int(sys.argv[3]), file_id)
    elif action == "latest_deduct":
        code = sys.argv[3] if len(sys.argv) > 3 else "R1"
        out = await _latest_deduct(int(sys.argv[2]), code)
    else:
        print(json.dumps({"error": f"unknown action {action}"}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

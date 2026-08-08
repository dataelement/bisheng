#!/usr/bin/env python3
"""G-M2 API 辅助：经 hooks/Facade 造数，供 Playwright 断言明细。

用法：
  cd src/backend && PYTHONPATH=. .venv/bin/python test/e2e_ui/points/helpers/gm2_trigger.py <action> ...
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 复用 factory 的 Gate 同步/轮询约定，避免 G-M2 在异步默认开启时读到旧余额。
from test.e2e_ui.points.helpers.factory_trigger import (  # noqa: E402
    _gate_award_mode,
    _wait_ledger,
)


async def _ensure_g7(tenant_id: int = 1) -> dict:
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.models import PointRule
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        existing = await repo.get_rule(tenant_id, "G7")
        if existing:
            if existing.status != "enabled":
                existing.status = "enabled"
                await repo.save_rule(existing)
                await session.commit()
            return {"ok": True, "created": False, "id": existing.id}
        rule = PointRule(
            tenant_id=tenant_id,
            rule_code="G7",
            rule_type="earn",
            name="文档库间分享",
            score_expr={"mode": "fixed", "score": 2},
            daily_cap=10,
            beneficiary="uploader",
            status="enabled",
            sort_order=7,
        )
        saved = await repo.save_rule(rule)
        await session.commit()
        return {"ok": True, "created": True, "id": saved.id}


async def _snapshot(user_id: int, rule_code: str) -> dict:
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        bal_row = (
            await session.execute(
                text(
                    "select coalesce(balance,0) from user_point_account "
                    "where tenant_id=1 and user_id=:u"
                ),
                {"u": user_id},
            )
        ).first()
        cnt_row = (
            await session.execute(
                text(
                    "select count(*) from user_point_log "
                    "where tenant_id=1 and user_id=:u and rule_code=:r and direction='earn'"
                ),
                {"u": user_id, "r": rule_code},
            )
        ).first()
        titles = (
            await session.execute(
                text(
                    "select title, delta, idempotency_key from user_point_log "
                    "where tenant_id=1 and user_id=:u and rule_code=:r and direction='earn' "
                    "order by id desc limit 5"
                ),
                {"u": user_id, "r": rule_code},
            )
        ).all()
    balance = int(bal_row[0]) if bal_row else 0
    count = int(cnt_row[0]) if cnt_row else 0
    return {
        "user_id": user_id,
        "rule_code": rule_code,
        "balance": balance,
        "count": count,
        "recent": [{"title": r[0], "delta": int(r[1]), "key": r[2]} for r in titles],
    }


async def _award_g2(user_id: int, file_id: int, space_id: int) -> dict:
    from bisheng.points.domain.services.points_award_hooks import notify_space_files_ready

    before = await _snapshot(user_id, "G2")
    with _gate_award_mode() as mode:
        await notify_space_files_ready(
            tenant_id=1,
            space_id=int(space_id),
            files=[SimpleNamespace(id=int(file_id))],
            uploader_id=int(user_id),
            is_favorite_space=False,
            space_level="department",
        )
    after = (
        await _snapshot(user_id, "G2")
        if mode == "sync"
        else await _wait_ledger(user_id, "G2", before)
    )
    return {"before": before, "after": after, "mode": mode}


async def _award_g7(user_id: int, share_entry_id: int) -> dict:
    from bisheng.points.domain.services.points_award_hooks import notify_document_shared

    before = await _snapshot(user_id, "G7")
    with _gate_award_mode() as mode:
        await notify_document_shared(
            tenant_id=1,
            share_entry_id=int(share_entry_id),
            source_space_id=10,
            target_space_id=12,
            uploader_id=int(user_id),
            sharer_id=int(user_id),
        )
    after = (
        await _snapshot(user_id, "G7")
        if mode == "sync"
        else await _wait_ledger(user_id, "G7", before)
    )
    return {"before": before, "after": after, "mode": mode}


async def _award_admin_g2(admin_uid: int, file_id: int) -> dict:
    from bisheng.points.domain.services.points_award_hooks import notify_space_files_ready

    before = await _snapshot(admin_uid, "G2")
    with _gate_award_mode() as mode:
        await notify_space_files_ready(
            tenant_id=1,
            space_id=10,
            files=[SimpleNamespace(id=int(file_id))],
            uploader_id=int(admin_uid),
            is_favorite_space=False,
            space_level="department",
        )
    after = (
        await _snapshot(admin_uid, "G2")
        if mode == "sync"
        else await _wait_ledger(admin_uid, "G2", before)
    )
    return {
        "before": before,
        "after": after,
        "mode": mode,
        "skipped": after["count"] == before["count"] and after["balance"] == before["balance"],
    }


async def _share_link_negative(user_id: int, fake_link_id: int) -> dict:
    """外链分享未挂 hooks：仅断言不会因 link_id 产生 earn:G7:{link_id} 流水。"""
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    key = f"earn:G7:{fake_link_id}"
    async with get_async_db_session() as session:
        row = (
            await session.execute(
                text(
                    "select count(*) from user_point_log "
                    "where tenant_id=1 and user_id=:u and idempotency_key=:k"
                ),
                {"u": user_id, "k": key},
            )
        ).first()
    return {"user_id": user_id, "key": key, "count": int(row[0]) if row else 0}


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "ensure_g7":
        out = await _ensure_g7()
    elif action == "award_g2":
        out = await _award_g2(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    elif action == "award_g7":
        out = await _award_g7(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "award_admin_g2":
        out = await _award_admin_g2(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "share_link_neg":
        out = await _share_link_negative(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "count_logs":
        out = await _snapshot(int(sys.argv[2]), sys.argv[3])
    elif action == "balance":
        out = await _snapshot(int(sys.argv[2]), "G2")
    else:
        print(json.dumps({"error": f"unknown action {action}"}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

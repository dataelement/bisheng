#!/usr/bin/env python3
"""F070 Gate 统一数据工厂：造数 / 对账 / 开关负例，供 G-M2~G-M5 复用。

用法：
  cd src/backend && PYTHONPATH=. config=config.yaml \\
    .venv/bin/python test/e2e_ui/points/helpers/factory_trigger.py <action> ...
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@contextmanager
def _gate_award_mode():
    """Gate 默认强制同步入账，避免依赖 Celery worker；POINTS_GATE_FORCE_SYNC=0 时走异步+轮询。"""
    force_sync = os.environ.get("POINTS_GATE_FORCE_SYNC", "1") != "0"
    if force_sync:
        with patch(
            "bisheng.points.domain.services.points_award_hooks._award_async_enabled",
            return_value=False,
        ):
            yield "sync"
    else:
        yield "async"


async def _wait_ledger(user_id: int, rule_code: str, before: dict, *, timeout_s: float = 15.0) -> dict:
    """轮询直到 earn 笔数或余额变化，或超时返回最后快照。"""
    deadline = time.time() + timeout_s
    after = before
    while time.time() < deadline:
        after = await _snapshot(user_id, rule_code)
        if after["count"] != before["count"] or after["balance"] != before["balance"]:
            return after
        await asyncio.sleep(0.3)
    return after


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
    return {
        "user_id": user_id,
        "rule_code": rule_code,
        "balance": int(bal_row[0]) if bal_row else 0,
        "count": int(cnt_row[0]) if cnt_row else 0,
        "recent": [{"title": r[0], "delta": int(r[1]), "key": r[2]} for r in titles],
    }


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
    return {"ok": True, "before": before, "after": after, "mode": mode}


async def _award_by_level(
    user_id: int,
    file_id: int,
    space_id: int,
    *,
    space_level: str,
    rule_code: str,
) -> dict:
    """按空间等级触发入库发分（G5=team / G6=team_ks）。"""
    from bisheng.points.domain.services.points_award_hooks import notify_space_files_ready

    before = await _snapshot(user_id, rule_code)
    with _gate_award_mode() as mode:
        await notify_space_files_ready(
            tenant_id=1,
            space_id=int(space_id),
            files=[SimpleNamespace(id=int(file_id))],
            uploader_id=int(user_id),
            is_favorite_space=False,
            space_level=space_level,
        )
    after = (
        await _snapshot(user_id, rule_code)
        if mode == "sync"
        else await _wait_ledger(user_id, rule_code, before)
    )
    return {
        "ok": True,
        "rule_code": rule_code,
        "space_level": space_level,
        "before": before,
        "after": after,
        "mode": mode,
    }


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
    return {"ok": True, "before": before, "after": after, "mode": mode}


async def _award_g3(user_id: int, file_id: int | None = None, favoriter_count: int = 75) -> dict:
    """直接经 Facade 造 G3 阶梯（不依赖真实收藏表）。"""
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository
    from bisheng.points.domain.services.points_award_facade import FavoriteChangedEvent, PointsAwardFacade
    from bisheng.points.domain.services.points_ledger_service import PointsLedgerService

    fid = int(file_id or (int(time.time()) % 1_000_000 + 920_000_000))
    before = await _snapshot(user_id, "G3")
    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        facade = PointsAwardFacade(repo, PointsLedgerService(repo), enabled=True)
        outcome = await facade.on_favorite_changed(
            FavoriteChangedEvent(
                tenant_id=1,
                file_id=fid,
                uploader_id=int(user_id),
                unique_favoriter_count=int(favoriter_count),
                space_manager_ids=frozenset(),
            )
        )
        await session.commit()
    after = await _snapshot(user_id, "G3")
    return {
        "ok": True,
        "file_id": fid,
        "skipped": outcome.skipped,
        "reason": outcome.reason,
        "before": before,
        "after": after,
    }


async def _award_g4(user_id: int, answer_id: int | None = None) -> dict:
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository
    from bisheng.points.domain.services.points_award_facade import AnswerAdoptedEvent, PointsAwardFacade
    from bisheng.points.domain.services.points_ledger_service import PointsLedgerService

    aid = int(answer_id or (int(time.time()) % 1_000_000 + 930_000_000))
    before = await _snapshot(user_id, "G4")
    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        facade = PointsAwardFacade(repo, PointsLedgerService(repo), enabled=True)
        outcome = await facade.on_answer_adopted(
            AnswerAdoptedEvent(tenant_id=1, answer_id=aid, answerer_id=int(user_id))
        )
        await session.commit()
    after = await _snapshot(user_id, "G4")
    return {
        "ok": True,
        "answer_id": aid,
        "skipped": outcome.skipped,
        "reason": outcome.reason,
        "before": before,
        "after": after,
    }


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
        "ok": True,
        "before": before,
        "after": after,
        "mode": mode,
        "skipped": after["count"] == before["count"] and after["balance"] == before["balance"],
    }


async def _share_link_neg(user_id: int, fake_link_id: int) -> dict:
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
    return {"ok": True, "user_id": user_id, "key": key, "count": int(row[0]) if row else 0}


async def _award_disabled(user_id: int, file_id: int | None = None) -> dict:
    """points.enabled=false 路径：Facade 覆盖关闭后不应入账。"""
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository
    from bisheng.points.domain.services.points_award_facade import PointsAwardFacade, SpaceFileReadyEvent
    from bisheng.points.domain.services.points_ledger_service import PointsLedgerService

    fid = int(file_id or (int(time.time()) % 1_000_000 + 940_000_000))
    before = await _snapshot(user_id, "G2")
    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        facade = PointsAwardFacade(repo, PointsLedgerService(repo), enabled=False)
        outcome = await facade.on_space_file_ready(
            SpaceFileReadyEvent(
                tenant_id=1,
                space_id=10,
                space_level="department",
                file_id=fid,
                uploader_id=int(user_id),
                is_favorite_space=False,
                space_manager_ids=frozenset(),
            )
        )
        await session.commit()
    after = await _snapshot(user_id, "G2")
    return {
        "ok": True,
        "file_id": fid,
        "skipped": outcome.skipped,
        "reason": outcome.reason,
        "before": before,
        "after": after,
        "no_new_log": after["count"] == before["count"],
    }


async def _reconcile(tenant_id: int = 1) -> dict:
    from bisheng.points.domain.services.points_reconcile_service import PointsReconcileService

    out = await PointsReconcileService().reconcile_tenant(int(tenant_id))
    return {"ok": True, **out}


async def _outbox_drain() -> dict:
    from bisheng.points.domain.services.points_sync_outbox_service import PointsSyncOutboxService

    out = await PointsSyncOutboxService().drain()
    return {"ok": True, **out}


async def _schema_check() -> dict:
    """MySQL 联调库：积分核心表是否可读。"""
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    required = [
        "user_point_account",
        "user_point_log",
        "point_rule",
        "point_copy",
        "point_rank_snapshot",
        "point_favorite_tier_award",
        "point_sync_outbox",
    ]
    missing: list[str] = []
    counts: dict[str, int] = {}
    has_org = False
    async with get_async_db_session() as session:
        for name in required:
            try:
                row = (await session.execute(text(f"select count(*) from {name}"))).first()
                counts[name] = int(row[0]) if row else 0
            except Exception:
                missing.append(name)
        # Dialect-safe: probe column via SELECT (no information_schema).
        try:
            await session.execute(text("select org_level from department limit 1"))
            has_org = True
        except Exception:
            has_org = False
    return {
        "ok": not missing and has_org,
        "missing_tables": missing,
        "counts": counts,
        "department_org_level": has_org,
    }


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "ensure_g7":
        out = await _ensure_g7()
    elif action == "award_g2":
        out = await _award_g2(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    elif action == "award_g5":
        # argv: user_id file_id space_id
        out = await _award_by_level(
            int(sys.argv[2]),
            int(sys.argv[3]),
            int(sys.argv[4]),
            space_level="team",
            rule_code="G5",
        )
    elif action == "award_g6":
        out = await _award_by_level(
            int(sys.argv[2]),
            int(sys.argv[3]),
            int(sys.argv[4]),
            space_level="team_ks",
            rule_code="G6",
        )
    elif action == "award_g7":
        out = await _award_g7(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "award_g3":
        fid = int(sys.argv[3]) if len(sys.argv) > 3 else None
        out = await _award_g3(int(sys.argv[2]), fid)
    elif action == "award_g4":
        aid = int(sys.argv[3]) if len(sys.argv) > 3 else None
        out = await _award_g4(int(sys.argv[2]), aid)
    elif action == "award_admin_g2":
        out = await _award_admin_g2(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "share_link_neg":
        out = await _share_link_neg(int(sys.argv[2]), int(sys.argv[3]))
    elif action == "award_disabled":
        fid = int(sys.argv[3]) if len(sys.argv) > 3 else None
        out = await _award_disabled(int(sys.argv[2]), fid)
    elif action == "reconcile":
        tid = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        out = await _reconcile(tid)
    elif action == "outbox_drain":
        out = await _outbox_drain()
    elif action == "schema_check":
        out = await _schema_check()
    elif action == "count_logs":
        out = await _snapshot(int(sys.argv[2]), sys.argv[3])
    else:
        print(json.dumps({"error": f"unknown action {action}"}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

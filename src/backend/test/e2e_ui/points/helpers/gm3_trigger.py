#!/usr/bin/env python3
"""G-M3 API 辅助：排行快照刷新 / org_level 只读检查 / 可选打标（需显式旗标）。

用法：
  cd src/backend && PYTHONPATH=. .venv/bin/python test/e2e_ui/points/helpers/gm3_trigger.py <action> ...

破坏性 set_company_root 仅当同时满足：
  E2E_POINTS_ALLOW_ORG_MUTATE=1
  E2E_POINTS_COMPANY_DEPT_ID=<dept_id>
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _org_levels(tenant_id: int = 1) -> dict:
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                text(
                    "select id, dept_id, name, parent_id, path, org_level "
                    "from department where tenant_id=:t and status='active' "
                    "and org_level is not null order by path"
                ),
                {"t": tenant_id},
            )
        ).all()
    items = [
        {
            "id": int(r[0]),
            "dept_id": r[1],
            "name": r[2],
            "parent_id": r[3],
            "path": r[4],
            "org_level": r[5],
        }
        for r in rows
    ]
    companies = [i for i in items if i["org_level"] == "company"]
    return {
        "ok": True,
        "count": len(items),
        "company_count": len(companies),
        "companies": companies,
        "levels": {
            "company": sum(1 for i in items if i["org_level"] == "company"),
            "dept": sum(1 for i in items if i["org_level"] == "dept"),
            "office": sum(1 for i in items if i["org_level"] == "office"),
            "squad": sum(1 for i in items if i["org_level"] == "squad"),
        },
        "sample": items[:20],
    }


async def _verify_cascade(tenant_id: int = 1) -> dict:
    """只读：若存在唯一 company 根，校验子树相对深度映射。"""
    from bisheng.points.domain.constants.org_levels import org_level_for_relative_depth, relative_depth
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    snap = await _org_levels(tenant_id)
    companies = snap["companies"]
    if len(companies) != 1:
        return {
            "ok": True,
            "skipped": True,
            "reason": f"expected exactly 1 company root, got {len(companies)}",
            "company_count": len(companies),
        }
    company = companies[0]
    root_path = company["path"] or f"/{company['id']}/"
    mismatches: list[dict] = []
    checked = 0
    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                text(
                    "select id, path, org_level from department "
                    "where tenant_id=:t and status='active' and path like :pfx "
                    "and org_level is not null"
                ),
                {"t": tenant_id, "pfx": f"{root_path}%"},
            )
        ).all()
    for row in rows:
        depth = relative_depth(root_path, row[1] or f"/{row[0]}/")
        if depth is None:
            continue
        expected = org_level_for_relative_depth(depth)
        checked += 1
        if row[2] != expected:
            mismatches.append(
                {
                    "id": int(row[0]),
                    "org_level": row[2],
                    "expected": expected,
                    "depth": depth,
                }
            )
    return {
        "ok": len(mismatches) == 0,
        "skipped": False,
        "company_id": company["id"],
        "checked": checked,
        "mismatches": mismatches[:10],
    }


async def _refresh_ranks(tenant_id: int = 1) -> dict:
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.points.domain.services.points_rank_service import PointsRankService

    set_current_tenant_id(tenant_id)
    out = await PointsRankService().refresh_rank_snapshots(tenant_id)
    return {"ok": True, **out}


async def _set_company_root(dept_id: str) -> dict:
    allow = os.environ.get("E2E_POINTS_ALLOW_ORG_MUTATE", "") == "1"
    if not allow:
        return {
            "ok": False,
            "skipped": True,
            "reason": "set E2E_POINTS_ALLOW_ORG_MUTATE=1 to clear/relabel tenant org_level",
        }
    from types import SimpleNamespace
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.points.domain.services.department_org_level_service import (
        DepartmentOrgLevelService,
    )

    set_current_tenant_id(1)
    admin = SimpleNamespace(is_admin=lambda: True, is_global_super=True, user_id=1)
    result = await DepartmentOrgLevelService().set_company_root(admin, dept_id)
    return {"ok": True, **result}


async def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"ok": False, "error": "missing action"}))
        return 1
    action = argv[0]
    if action == "org_levels":
        out = await _org_levels()
    elif action == "verify_cascade":
        out = await _verify_cascade()
    elif action == "refresh_ranks":
        out = await _refresh_ranks()
    elif action == "set_company_root":
        dept_id = argv[1] if len(argv) > 1 else os.environ.get("E2E_POINTS_COMPANY_DEPT_ID", "")
        if not dept_id:
            out = {
                "ok": False,
                "skipped": True,
                "reason": "missing dept_id / E2E_POINTS_COMPANY_DEPT_ID",
            }
        else:
            out = await _set_company_root(str(dept_id))
    else:
        out = {"ok": False, "error": f"unknown action: {action}"}
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))

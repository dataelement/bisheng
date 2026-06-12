#!/usr/bin/env python3
"""Backfill WEB_MENU ``linsight_task_mode`` for roles that already have ``home`` (F035).

Why this exists
---------------
Before F035, the 灵思任务模式 entry (``/linsight``) shared the same ``home`` menu
permission as日常对话 (``/c``). F035 splits it into its own sub-toggle
``linsight_task_mode`` (under 首页, a workstation child). After upgrade the
``/linsight`` route guard checks ``linsight_task_mode`` instead of ``home``, so any
existing role that could enter 任务模式 (i.e. already has ``home``) must be granted
the new key — otherwise升级后 those users lose access (regression). See PRD §4.7.7
FR-7.11 and design §6.7.

What it does
------------
For every (role_id, tenant_id) that has WEB_MENU ``home`` but not yet
``linsight_task_mode``, insert a ``linsight_task_mode`` WEB_MENU row inheriting the
same tenant_id. Idempotent & re-runnable: rows that already exist are skipped.

How to run (from src/backend/)
------------------------------
    export config=config.yaml        # must match the running service
    export PYTHONPATH="./"
    python scripts/backfill_linsight_task_mode_web_menu.py            # dry-run (default, no writes)
    python scripts/backfill_linsight_task_mode_web_menu.py --apply    # actually write rows
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.role_access import (  # noqa: E402
    AccessType,
    RoleAccess,
    WebMenuResource,
)

WEB_MENU = AccessType.WEB_MENU.value
HOME = WebMenuResource.HOME.value
LINSIGHT_TASK_MODE = WebMenuResource.LINSIGHT_TASK_MODE.value


async def run(apply: bool) -> int:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            home_rows = (
                await session.exec(
                    select(RoleAccess).where(
                        RoleAccess.type == WEB_MENU,
                        RoleAccess.third_id == HOME,
                    )
                )
            ).all()
            existing_rows = (
                await session.exec(
                    select(RoleAccess).where(
                        RoleAccess.type == WEB_MENU,
                        RoleAccess.third_id == LINSIGHT_TASK_MODE,
                    )
                )
            ).all()

        existing_keys = {(r.role_id, r.tenant_id) for r in existing_rows}
        seen: set[tuple] = set()
        to_create: list[tuple] = []
        for r in home_rows:
            key = (r.role_id, r.tenant_id)
            if key in existing_keys or key in seen:
                continue
            seen.add(key)
            to_create.append(key)
            if apply:
                session.add(
                    RoleAccess(
                        role_id=r.role_id,
                        type=WEB_MENU,
                        third_id=LINSIGHT_TASK_MODE,
                        tenant_id=r.tenant_id,
                    )
                )

        if apply and to_create:
            await session.commit()

    summary = {
        "apply": apply,
        "roles_with_home": len({(r.role_id, r.tenant_id) for r in home_rows}),
        "already_had_linsight_task_mode": len(existing_keys),
        "backfilled": len(to_create),
        "backfilled_keys": [{"role_id": rid, "tenant_id": tid} for rid, tid in to_create],
    }
    if not apply:
        print(f"[dry-run] would backfill {len(to_create)} role(s) — pass --apply to write")
    else:
        print(f"[done] backfilled {len(to_create)} role(s) with '{LINSIGHT_TASK_MODE}'")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write rows (default: dry-run, no writes)")
    args = parser.parse_args()

    async def _main() -> int:
        try:
            return await run(args.apply)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
